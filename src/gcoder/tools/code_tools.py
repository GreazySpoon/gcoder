# src/gcoder/tools/code_tools.py

import asyncio
import os
from pathlib import Path
from typing import Optional, Dict, Any

from google.adk.tools import ToolContext
# This assumes you have copied your 'lsp' directory to 'src/gcoder/lsp/'
from gcoder.lsp.lsp_manager import LspManager

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
                "message": "Could not start or connect to a language server for this file type. Ensure the necessary LSP server is installed and in your PATH."
            }

        file_content = full_path.read_text(encoding='utf-8', errors='ignore')
        file_uri = full_path.as_uri()

        async with client as lsp:
            await lsp.notify_did_open(str(full_path), file_content)
            await asyncio.sleep(0.5) # Allow time for server to process

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


async def find_definition_reference(tool_context: ToolContext, symbol: str, file_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Asynchronously finds the definition of a symbol and all its references across the workspace using LSP.
    If multiple definitions exist, it will ask to re-run with a specific 'file_path'.

    Args:
        symbol (str): The symbol (e.g., function or class name) to search for.
        file_path (Optional[str]): The specific file where the symbol's definition is located, if multiple exist.
    """
    cwd = tool_context.state.get('cwd')
    workspace_root = tool_context.state.get('git_root', cwd)
    if not workspace_root:
        return {"status": "error", "message": "This tool requires a workspace root (ideally a Git repository) to function."}

    lsp_manager = LspManager(workspace_root)

    # --- FIX: Dynamically find a relevant file to initialize the server ---
    # Instead of guessing 'main.py', find the first available file for the dominant language.
    # This is far more robust and won't crash if a specific filename doesn't exist.
    init_file_path = None
    file_extensions = ('.py', '.js', '.ts', '.cs') # Add other language extensions if needed
    for root, _, files in os.walk(workspace_root):
        # Avoid searching in virtual environments or node_modules for efficiency
        if 'venv' in root or '.venv' in root or 'node_modules' in root:
            continue
        for file in files:
            if file.endswith(file_extensions):
                init_file_path = os.path.join(root, file)
                break
        if init_file_path:
            break
    
    if not init_file_path:
        return {"status": "error", "message": "Could not find any source code files (.py, .js, .ts, .cs) in the workspace to initialize the language server."}
    # --- END FIX ---

    client = await lsp_manager.get_client(init_file_path)
    if not client:
        return {"status": "error", "message": "Could not start or connect to a language server for this project."}

    try:
        async with client as lsp:
            # Step 1: Explicitly open a known source file. This helps the server
            # orient itself and kickstarts the indexing process.
            init_file_content = Path(init_file_path).read_text(encoding='utf-8', errors='ignore')
            await lsp.notify_did_open(init_file_path, init_file_content)

            # Step 2: Wait for indexing. This is crucial. We must give the server
            # time to scan the workspace after initialization.
            await asyncio.sleep(2.5)

            # Now, the server is ready for a workspace-wide query.
            w_symbol_params = {"query": symbol}
            symbol_response = await lsp.execute_request("workspace/symbol", w_symbol_params)
            
            definitions = symbol_response.get('result', [])
            if not definitions:
                return {"status": "success", "content": f"Symbol '{symbol}' not found in the workspace."}

            target_definition = None
            if len(definitions) > 1:
                if not file_path:
                    locations = [Path(d['location']['uri'].replace('file://', '')).relative_to(workspace_root) for d in definitions]
                    return {
                        "status": "success",
                        "content": (f"Found multiple definitions for '{symbol}'. Please specify the 'file_path'.\n"
                                    f"Possible locations:\n- " + "\n- ".join(map(str, locations)))
                    }
                
                target_uri = (Path(workspace_root) / file_path).as_uri()
                for d in definitions:
                    if d['location']['uri'] == target_uri:
                        target_definition = d
                        break
                if not target_definition:
                    return {"status": "error", "message": f"Symbol '{symbol}' not found in the specified file '{file_path}'."}
            else:
                target_definition = definitions[0]

            def_location = target_definition['location']
            def_uri = def_location['uri']
            def_path = Path(def_uri.replace('file://', ''))
            def_pos = def_location['range']['start']

            ref_params = {'textDocument': {'uri': def_uri}, 'position': def_pos, 'context': {'includeDeclaration': False}}
            references_response = await lsp.execute_request('textDocument/references', ref_params)
            references = references_response.get('result', [])

            def_range = def_location['range']
            def_start_line = def_range['start']['line'] + 1
            def_end_line = def_range['end']['line'] + 1
            
            definition_snippet = _read_file_snippet(def_path, def_start_line, def_end_line)

            output = [f"**Definition & References for `{symbol}`**\n"]
            relative_def_path = def_path.relative_to(workspace_root)
            output.append(f"--- Definition in `{relative_def_path}` (Lines {def_start_line}-{def_end_line}) ---")
            output.append(f"```\n{definition_snippet}\n```")

            output.append(f"\n--- Found {len(references)} References ---")
            if not references:
                output.append("No other references found in the workspace.")
            else:
                for ref in sorted(references, key=lambda r: (r['uri'], r['range']['start']['line'])):
                    ref_path_str = Path(ref['uri'].replace('file://', '')).relative_to(workspace_root)
                    ref_line = ref['range']['start']['line'] + 1
                    output.append(f"- `{ref_path_str}` on line `{ref_line}`")
            
            return {"status": "success", "content": "\n".join(output)}

    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred during symbol search: {e}"}