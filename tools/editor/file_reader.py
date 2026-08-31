import os
import re

def read_file_with_line_numbers(repo_path: str, filepath: str, start_line: int = None, end_line: int = None) -> str:
    """Read a repository file and return its content with line numbers for the LLM."""
    safe_path = os.path.normpath(filepath).lstrip(os.sep)
    full_path = os.path.abspath(os.path.join(repo_path, safe_path))
    repo_root = os.path.abspath(repo_path)

    if not full_path.startswith(repo_root + os.sep) and full_path != repo_root:
        return f"Error reading file: '{filepath}' escapes the repository."
    if not full_path.endswith(".go"):
        return f"Error reading file: '{filepath}' is not a Go source file."

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return f"Error reading file: {exc}"

    start_idx = max(0, start_line - 1) if start_line is not None else 0
    end_idx = min(len(lines), end_line) if end_line is not None else len(lines)
    
    if start_idx >= len(lines):
        return f"Error: start_line {start_line} is beyond the end of the file."
        
    return "\n".join(f"{n} | {lines[n-1]}" for n in range(start_idx + 1, end_idx + 1))


def read_function(repo_path: str, filepath: str, function_name: str) -> str:
    """Extract a single Go function by name using brace-counting (no AST needed)."""
    safe_path = os.path.normpath(filepath).lstrip(os.sep)
    full_path = os.path.abspath(os.path.join(repo_path, safe_path))
    repo_root = os.path.abspath(repo_path)

    if not full_path.startswith(repo_root + os.sep) and full_path != repo_root:
        return f"Error: '{filepath}' escapes the repository."
    if not full_path.endswith(".go"):
        return f"Error: '{filepath}' is not a Go source file."

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception as exc:
        return f"Error reading file: {exc}"

    if "." in function_name: function_name = function_name.split(".")[-1]
    function_name = re.sub(r"[()*]", "", function_name).strip()

    func_pattern = re.compile(r"^\s*func\s+(?:(?:\([^)]+\)\s+)?)?" + re.escape(function_name) + r"\b(?:\s*\[[^\]]+\])?\s*\(")

    start_idx = next((i for i, l in enumerate(lines) if func_pattern.match(l)), -1)
    if start_idx == -1: return f"Error: Function '{function_name}' not found in {filepath}."

    brace_count = 0
    in_func, in_block_comment, in_raw_string = False, False, False
    end_idx = len(lines) - 1

    for i in range(start_idx, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            if in_block_comment:
                if line[j:j+2] == "*/":
                    in_block_comment = False; j += 2
                else: j += 1
                continue
            if in_raw_string:
                if line[j] == "`": in_raw_string = False
                j += 1
                continue
            if line[j:j+2] == "//": break
            if line[j:j+2] == "/*": in_block_comment = True; j += 2; continue
            if line[j] == "`": in_raw_string = True; j += 1; continue
            if line[j] == '"':
                j += 1
                while j < len(line) and line[j] != '"': j += 2 if line[j] == "\\" else 1
                j += 1
                continue
            if line[j] == "'":
                j += 1
                while j < len(line) and line[j] != "'": j += 2 if line[j] == "\\" else 1
                j += 1
                continue
            if line[j] == "{":
                brace_count += 1; in_func = True
            elif line[j] == "}":
                brace_count -= 1
            j += 1

        if in_func and brace_count == 0:
            end_idx = i; break

    snippet = "\n".join(lines[start_idx:end_idx + 1])
    return f"// Extracted from {filepath} (Lines {start_idx + 1}-{end_idx + 1})\n{snippet}"
