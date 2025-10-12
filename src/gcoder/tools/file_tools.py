# src/gcoder/tools/file_tools.py

import os
import tempfile
import shutil
from typing import Optional, Dict, Any

from google.adk.tools import ToolContext

def read_file(tool_context: ToolContext, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
    """
    Reads a specific range of lines from a file, prefixed with line numbers.
    If start_line is not provided, it defaults to 1.
    If end_line is not provided, it defaults to 200 lines after the start line.
    """
    try:
        actual_start_line = start_line if start_line is not None else 1
        actual_end_line = end_line if end_line is not None else (actual_start_line + 199)

        cwd = tool_context.state.get('cwd', os.getcwd())
        full_path = os.path.join(cwd, path)
        if not os.path.isfile(full_path):
            return {"status": "error", "message": f"File '{path}' is not a file or does not exist."}
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        start_idx = max(0, actual_start_line - 1)
        end_idx = min(total_lines, actual_end_line)

        if start_idx >= total_lines:
            return {"status": "error", "message": f"Cannot read from start_line {actual_start_line}. The file only has {total_lines} lines."}

        line_range_str = f"Lines {start_idx + 1}-{end_idx} of {total_lines}"
        numbered_lines = [f"{i + 1:>4} | {lines[i].rstrip()}" for i in range(start_idx, end_idx)]
        content_snippet = "\n".join(numbered_lines)
        report = f"--- Content of {path} ({line_range_str}) ---\n{content_snippet}"
        return {"status": "success", "content": report}
    except Exception as e:
        return {"status": "error", "message": f"Error reading file: {e}"}

def write_file(tool_context: ToolContext, path: str, content: str) -> Dict[str, Any]:
    """Writes content to a file, completely overwriting it if it exists. Creates directories if needed."""
    try:
        cwd = tool_context.state.get('cwd', os.getcwd())
        full_path = os.path.join(cwd, path)
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        message = f"Successfully wrote {len(content.splitlines())} lines to '{path}'."
        return {"status": "success", "content": message}
    except Exception as e:
        return {"status": "error", "message": f"Error writing file: {e}"}

def edit_file(tool_context: ToolContext, path: str, start_line: int, end_line: int, new_content: str) -> Dict[str, Any]:
    """Replaces a contiguous block of lines in a file with new content."""
    try:
        cwd = tool_context.state.get('cwd', os.getcwd())
        full_path = os.path.join(cwd, path)
        if not os.path.isfile(full_path):
            return {"status": "error", "message": f"Cannot edit file. '{path}' does not exist."}

        if start_line < 1:
            return {"status": "error", "message": "`start_line` must be 1 or greater."}
        if start_line > end_line + 1:
            return {"status": "error", "message": f"Invalid range. `start_line` ({start_line}) cannot be greater than `end_line` ({end_line}) + 1."}
        
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        if start_idx > end_idx:
            end_idx = start_idx
        
        new_content_lines = new_content.splitlines(True)
        if not new_content_lines and new_content:
            new_content_lines = [new_content]
            
        lines[start_idx:end_idx] = new_content_lines

        temp_dir = os.path.dirname(full_path)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, dir=temp_dir) as temp_f:
            temp_path = temp_f.name
            temp_f.writelines(lines)
        
        shutil.move(temp_path, full_path)
        
        if start_line > end_line:
            message = f"Successfully inserted content at line {start_line} in '{path}'."
        else:
            message = f"Successfully replaced lines {start_line}-{end_line} in '{path}'."
        return {"status": "success", "content": message}
    except Exception as e:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)
        return {"status": "error", "message": f"An unexpected error occurred while editing file: {e}"}

def find_file(tool_context: ToolContext, filename: str, path: Optional[str] = None) -> Dict[str, Any]:
    """Recursively finds all occurrences of a file by its name in a given directory."""
    try:
        actual_path = path if path is not None else "."
        cwd = tool_context.state.get('cwd', os.getcwd())
        search_path = os.path.join(cwd, actual_path)
        found_files = []
        for root, _, files in os.walk(search_path):
            if filename in files:
                full_path = os.path.join(root, filename)
                relative_path = os.path.relpath(full_path, cwd)
                found_files.append(relative_path)
        
        if not found_files:
            return {"status": "success", "content": f"File '{filename}' not found in '{actual_path}'."}
        
        report = f"Found '{filename}' at the following locations:\n- " + "\n- ".join(found_files)
        return {"status": "success", "content": report}
    except Exception as e:
        return {"status": "error", "message": f"Error finding file: {e}"}

def search_text(tool_context: ToolContext, search_term: str, path: Optional[str] = None) -> Dict[str, Any]:
    """Recursively searches for a text string in all files within a directory."""
    try:
        actual_path = path if path is not None else "."
        cwd = tool_context.state.get('cwd', os.getcwd())
        search_path = os.path.join(cwd, actual_path)
        results = []
        
        for root, _, files in os.walk(search_path):
            for file in files:
                full_path = os.path.join(root, file)
                file_matches = []
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    for i, line in enumerate(lines):
                        if search_term in line:
                            file_matches.append(f"  Line {i + 1}: {line.strip()}")
                except Exception:
                    continue

                if file_matches:
                    relative_path = os.path.relpath(full_path, cwd)
                    results.append(f"\n# {relative_path}:")
                    results.extend(file_matches)
        
        if not results:
            return {"status": "success", "content": f"No occurrences of '{search_term}' found in '{actual_path}'."}
        
        header = f"Search results for '{search_term}' in '{actual_path}':\n"
        report = header + "\n".join(results)
        return {"status": "success", "content": report}
    except Exception as e:
        return {"status": "error", "message": f"Error searching for text: {e}"}