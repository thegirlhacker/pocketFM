import os

def _get_full_path(repo_path: str, filepath: str) -> str:
    safe_path = os.path.normpath(filepath).lstrip(os.sep)
    return os.path.abspath(os.path.join(repo_path, safe_path))

def edit_file_tool(repo_path: str, filepath: str, old_snippet: str, new_snippet: str) -> str:
    """Replaces old_snippet with new_snippet in filepath."""
    full_path = _get_full_path(repo_path, filepath)
    if not os.path.exists(full_path): return f"Error: File '{filepath}' does not exist."
        
    try:
        with open(full_path, "r", encoding="utf-8") as f: content = f.read()
        if old_snippet not in content: return "Error: old_snippet not found in file."
        
        occurrences = content.count(old_snippet)
        if occurrences > 1: return f"Error: old_snippet found {occurrences} times. Make your old_snippet more specific."
            
        with open(full_path, "w", encoding="utf-8") as f: f.write(content.replace(old_snippet, new_snippet))
        return f"Successfully updated {filepath}."
    except Exception as exc: return f"Error editing file: {exc}"

def create_file_tool(repo_path: str, filepath: str, content: str) -> str:
    """Creates a new file with the given content."""
    full_path = _get_full_path(repo_path, filepath)
    if os.path.exists(full_path): return f"Error: File '{filepath}' already exists."
    
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f: f.write(content)
        return f"Successfully created {filepath}."
    except Exception as exc: return f"Error creating file: {exc}"

def delete_file_tool(repo_path: str, filepath: str) -> str:
    """Deletes the specified file."""
    full_path = _get_full_path(repo_path, filepath)
    if not os.path.exists(full_path): return f"Error: File '{filepath}' does not exist."
    
    try:
        os.remove(full_path)
        return f"Successfully deleted {filepath}."
    except Exception as exc: return f"Error deleting file: {exc}"

def replace_lines_tool(repo_path: str, filepath: str, start_line: int, end_line: int, new_content: str) -> str:
    """Replaces lines from start_line to end_line (inclusive) with new_content."""
    full_path = _get_full_path(repo_path, filepath)
    if not os.path.exists(full_path): return f"Error: File '{filepath}' does not exist."
    
    try:
        with open(full_path, "r", encoding="utf-8") as f: lines = f.read().splitlines()
        
        start_idx = max(0, start_line - 1)
        end_idx = min(len(lines), end_line)
        
        if start_idx >= len(lines): return f"Error: start_line {start_line} is beyond file end."
        
        # Replace the slice with new_content split into lines
        new_lines = new_content.splitlines() if new_content else []
        lines[start_idx:end_idx] = new_lines
        
        with open(full_path, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
        return f"Successfully replaced lines {start_line}-{end_line} in {filepath}."
    except Exception as exc: return f"Error replacing lines: {exc}"
