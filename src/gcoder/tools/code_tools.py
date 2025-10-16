# src/gcoder/tools/code_tools.py

import asyncio
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from google.adk.tools import ToolContext
from gcoder.lsp.lsp_manager import LspManager

# --- HELPER FUNCTION (Internal) ---
def _read_file_snippet(full_path: Path, start_line: int, end_line: int) -> str:
    """A self-contained helper to read a snippet from a file."""
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        
        snippet_lines = [line.rstrip() for line in lines[start_idx:end_idx]]
        return "\n".join(snippet_lines)
    except Exception:
        return f"Error: Could not read snippet from {full_path}."

# --- TOOL 1: FIND DEFINITION (The "Where?") ---
async def find_definition(tool_context: ToolContext, symbol: str) -> Dict[str, Any]:
    """
    Locates the definition(s) of a symbol (class or function) within the workspace.
    This is the first step to understanding a piece of code. It returns structured location data.
    
    Args:
        symbol (str): The name of the class or function to find.
    """
    cwd = tool_context.state.get('cwd')
    workspace_root = tool_context.state.get('git_root', cwd)
    if not workspace_root:
        return {"status": "error", "message": "This tool requires a workspace root to function."}

    lsp_manager = LspManager(workspace_root)

    # Find a source file to initialize the LSP server context
    init_file_path = None
    file_extensions = ('.py', '.js', '.ts', '.cs')
    for root, _, files in os.walk(workspace_root):
        if 'venv' in root or '.venv' in root or 'node_modules' in root: continue
        for file in files:
            if file.endswith(file_extensions):
                init_file_path = os.path.join(root, file)
                break
        if init_file_path: break
    
    if not init_file_path:
        return {"status": "error", "message": "Could not find any source code files to initialize the language server."}

    client = await lsp_manager.get_client(init_file_path)
    if not client:
        return {"status": "error", "message": "Could not start or connect to a language server for this project."}

    try:
        async with client as lsp:
            init_file_content = Path(init_file_path).read_text(encoding='utf-8', errors='ignore')
            await lsp.notify_did_open(init_file_path, init_file_content)
            
            # Give server more time to index the workspace
            await asyncio.sleep(8)  # Increased time for indexing

            # Robust retry loop to wait for server indexing
            definitions_result = []
            max_retries = 8
            for attempt in range(max_retries):
                symbol_response = await lsp.execute_request("workspace/symbol", {"query": symbol})
                definitions_result = symbol_response.get('result', [])
                if definitions_result:
                    break
                print(f"LSP: Symbol '{symbol}' not found on attempt {attempt + 1}/{max_retries}. Retrying as server may be indexing...")
                await asyncio.sleep(2)

            if not definitions_result:
                return {"status": "not_found", "message": f"Symbol '{symbol}' not found in the workspace after {max_retries} attempts."}

            # Format the output into a clean, structured list
            formatted_definitions = []
            for d in definitions_result:
                loc = d.get('location', {})
                uri = loc.get('uri', '').replace('file://', '')
                if not uri: continue
                
                start = loc.get('range', {}).get('start', {})
                end = loc.get('range', {}).get('end', {})
                
                formatted_definitions.append({
                    "file_path": str(Path(uri).relative_to(workspace_root)),
                    "line_number": start.get('line', -1) + 1,
                    "character": start.get('character', -1) + 1,
                    "start_line": start.get('line', -1) + 1,
                    "end_line": end.get('line', -1) + 1
                })
            
            return {"status": "success", "definitions": formatted_definitions}

    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred during symbol search: {e}"}

# --- TOOL 2: GET DEFINITION CODE (The "What?") ---
async def get_definition_code(tool_context: ToolContext, file_path: str, start_line: int, end_line: int) -> Dict[str, Any]:
    """
    Retrieves the source code of a definition from a file, given its location.
    Use the location data provided by the 'find_definition' tool.

    Args:
        file_path (str): The relative path to the file containing the definition.
        start_line (int): The starting line number of the definition.
        end_line (int): The ending line number of the definition.
    """
    cwd = tool_context.state.get('cwd')
    if not cwd:
        return {"status": "error", "message": "Could not determine current working directory."}
    
    full_path = Path(cwd) / file_path
    if not full_path.is_file():
        return {"status": "error", "message": f"File not found: {full_path}"}
        
    code_snippet = _read_file_snippet(full_path, start_line, end_line)
    if "Error:" in code_snippet:
        return {"status": "error", "message": code_snippet}
    
    return {"status": "success", "code": code_snippet}

# --- TOOL 3: FIND REFERENCES (The "Who?") ---
async def find_references(tool_context: ToolContext, file_path: str, line_number: int, character: int) -> Dict[str, Any]:
    """
    Finds all references to a symbol, given its exact definition location.
    Use the location data provided by the 'find_definition' tool.

    Args:
        file_path (str): The relative path to the file containing the definition.
        line_number (int): The line number where the definition is located.
        character (int): The character position on the line where the definition starts.
    """
    cwd = tool_context.state.get('cwd')
    workspace_root = tool_context.state.get('git_root', cwd)
    if not workspace_root:
        return {"status": "error", "message": "This tool requires a workspace root to function."}

    full_path = Path(workspace_root) / file_path
    if not full_path.is_file():
        return {"status": "error", "message": f"File not found: {full_path}"}

    lsp_manager = LspManager(workspace_root)
    client = await lsp_manager.get_client(str(full_path))
    if not client:
        return {"status": "error", "message": "Could not connect to a language server for this project."}

    try:
        async with client as lsp:
            file_content = full_path.read_text(encoding='utf-8', errors='ignore')
            await lsp.notify_did_open(str(full_path), file_content)
            await asyncio.sleep(2)  # Allow server to process the open file

            ref_params = {
                'textDocument': {'uri': full_path.as_uri()},
                'position': {'line': line_number - 1, 'character': character - 1},
                'context': {'includeDeclaration': False}
            }
            references_response = await lsp.execute_request('textDocument/references', ref_params)
            references_result = references_response.get('result', [])

            if not references_result:
                return {"status": "success", "references": []}

            formatted_references = []
            for ref in references_result:
                uri = ref.get('uri', '').replace('file://', '')
                if not uri: continue
                
                start = ref.get('range', {}).get('start', {})
                formatted_references.append({
                    "file_path": str(Path(uri).relative_to(workspace_root)),
                    "line_number": start.get('line', -1) + 1,
                    "character": start.get('character', -1) + 1
                })
            
            return {"status": "success", "references": formatted_references}

    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred finding references: {e}"}


# --- Existing Inspect File Tool (works well, no changes needed) ---
async def inspect_file(tool_context: ToolContext, file_path: str) -> Dict[str, Any]:
    """
    Asynchronously analyzes a source code file to find errors, warnings, and its overall structure using LSP.
    This is useful for understanding code before modifying it.
    
    Args:
        file_path (str): The relative path to the source code file.
    """
    cwd = tool_context.state.get('cwd')
    if not cwd:
        return {"status": "error", "message": "Could not determine current working directory from state."}

    full_path = Path(cwd) / file_path
    if not full_path.is_file():
        return {"status": "error", "message": f"File not found at '{full_path}'"}

    workspace_root = tool_context.state.get('git_root', cwd)
    lsp_manager = LspManager(workspace_root)
    
    try:
        client = await lsp_manager.get_client(str(full_path))
        if not client:
            return {
                "status": "error", 
                "message": "Could not start or connect to a language server for this file type."
            }

        file_content = full_path.read_text(encoding='utf-8', errors='ignore')
        file_uri = full_path.as_uri()

        async with client as lsp:
            await lsp.notify_did_open(str(full_path), file_content)
            await asyncio.sleep(0.5)

            diag_params = {"textDocument": {"uri": file_uri}}
            diag_response = await lsp.execute_request("textDocument/diagnostic", diag_params)
            
            symbol_params = {"textDocument": {"uri": file_uri}}
            symbol_response = await lsp.execute_request("textDocument/documentSymbol", symbol_params)

        output = [f"**Inspection Report for: `{file_path}`**\n"]
        output.append("--- Diagnostics ---")
        diags = diag_response.get('result', {}).get('items', [])
        if not diags:
            output.append("No errors or warnings found.")
        else:
            for d in diags:
                line = d['range']['start']['line'] + 1
                severity = {1: 'Error', 2: 'Warning', 3: 'Info', 4: 'Hint'}.get(d.get('severity', 3))
                output.append(f"- **{severity}** on line `{line}`: {d['message'].strip()}")

        output.append("\n--- File Structure ---")
        symbols = symbol_response.get('result', [])
        if not symbols:
            output.append("Could not determine file structure.")
        else:
            def format_symbols(symbol_list, indent_level=0):
                for s in symbol_list:
                    kind_map = {5: "Class", 6: "Method", 12: "Function", 13: "Variable"}
                    kind_str = kind_map.get(s.get('kind'), f"Kind-{s.get('kind')}")
                    name = s.get('name', 'N/A')
                    indent = "  " * indent_level
                    output.append(f"{indent}- `{name}` ({kind_str})")
                    if 'children' in s and s['children']:
                        format_symbols(s['children'], indent_level + 1)
            format_symbols(symbols)

        return {"status": "success", "content": "\n".join(output)}

    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred during file inspection: {e}"}