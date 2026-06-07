import subprocess
import os
import re
import shutil
from tools.editor.file_reader import read_file_with_line_numbers

def extract_failing_files(output: str) -> set[str]:
    """Extracts filenames from Go compiler or test errors (e.g., utils.go:12:3)."""
    pattern = r"(?m)^([a-zA-Z0-9_\-\./\\]+\.go):\d+:"
    return set(re.findall(pattern, output))

def get_failing_files_context(repo_path: str, files: set[str]) -> str:
    """Reads the contents of the files that broke so the LLM can fix them."""
    context = ""
    for f in files:
        # Ignore files that are outside the repo
        if not os.path.exists(os.path.join(repo_path, f)):
            continue
        context += f"\n--- {f} ---\n"
        # Truncate if the file is insanely large, but read_file_with_line_numbers is safe
        file_content = read_file_with_line_numbers(repo_path, f)
        if len(file_content) > 15000:
            file_content = file_content[:15000] + "\n...[TRUNCATED]..."
        context += file_content
    return context

def run_go_validation(repo_path: str, modified_files: list[str]) -> tuple[bool, str, str]:
    """
    Implements the 'Medium Way' Validation Flow:
    Returns: (success_boolean, error_message, failing_files_context)
    """
    if not shutil.which("go"):
        return True, "Validation skipped: 'go' executable not found in PATH.", ""

    if not os.path.exists(os.path.join(repo_path, "go.mod")):
        return False, "Not a Go repository (no go.mod found).", ""

    # --- STEP 1: The Quick Syntax Check (Local Test) ---
    target_dirs = set()
    for f in modified_files:
        d = os.path.dirname(f)
        target_dirs.add(f"./{d}" if d else ".")
    
    if not target_dirs:
        target_dirs = ["./..."]

    for target in target_dirs:
        local_test = subprocess.run(
            ["go", "test", target],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if local_test.returncode != 0:
            err_out = local_test.stdout + "\n" + local_test.stderr
            return False, f"STEP 1 Local Test Failed for package {target}:\n{err_out}", ""

    # --- STEP 2: The Blast Radius Check (Global Build + Test) ---
    build_process = subprocess.run(
        ["go", "build", "./..."],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    if build_process.returncode != 0:
        err_out = build_process.stderr
        failing_files = extract_failing_files(err_out)
        context = get_failing_files_context(repo_path, failing_files)
        return False, f"STEP 2 Global Build Failed (Blast Radius Check):\n{err_out}", context

    test_process = subprocess.run(
        ["go", "test", "./..."],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    if test_process.returncode != 0:
        err_out = test_process.stdout + "\n" + test_process.stderr
        failing_files = extract_failing_files(err_out)
        context = get_failing_files_context(repo_path, failing_files)
        return False, f"STEP 2 Global Test Failed (Blast Radius Check):\n{err_out}", context

    # --- STEP 3: Success! ---
    return True, "Validation successful. Local and Global tests passed.", ""

