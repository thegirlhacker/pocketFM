import re
import subprocess
import os
import tempfile

def revert_repo(repo_path: str):
    """Hard resets the repository to discard any applied diffs during retries."""
    subprocess.run(["git", "reset", "--hard"], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, capture_output=True)

def extract_modified_files(diff_text: str, repo_path: str = None) -> list[str]:
    """Parses the diff to find which files are being modified. Fallback to git status if no diff."""
    files = []
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].split('\t')[0].strip()
            if path.startswith("a/") or path.startswith("b/"): path = path[2:]
            if path != "/dev/null": files.append(path)
            
    if not files and repo_path:
        status = subprocess.run(["git", "diff", "--name-only"], cwd=repo_path, capture_output=True, text=True)
        files = [f.strip() for f in status.stdout.splitlines() if f.strip()]
        
    return list(dict.fromkeys(files))

def apply_git_diff(repo_path: str, final_fix: str) -> tuple[bool, str]:
    """Extracts the diff from the LLM output and applies it to the repository."""
    cleaned_fix = (final_fix or "").strip()
    unified_diff = _extract_unified_diff(cleaned_fix)
    
    if not unified_diff:
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
        if status.stdout.strip(): return True, "Modifications applied via tools (no diff in final text)."
        return False, "No valid unified diff found and no files modified via tools."

    fd, temp_path = tempfile.mkstemp(suffix=".diff")
    with os.fdopen(fd, 'w') as f: f.write(unified_diff + "\n")

    errors = []
    try:
        process = subprocess.run(["git", "apply", "--ignore-space-change", "--ignore-whitespace", temp_path], cwd=repo_path, capture_output=True, text=True)
        if process.returncode == 0: return True, "Diff applied successfully."
        errors.append(f"git apply -p1 error: {process.stderr.strip()}")

        process_p0 = subprocess.run(["git", "apply", "-p0", "--ignore-space-change", "--ignore-whitespace", temp_path], cwd=repo_path, capture_output=True, text=True)
        if process_p0.returncode == 0: return True, "Diff applied successfully with git apply -p0."
        errors.append(f"git apply -p0 error: {process_p0.stderr.strip()}")

        patch_process = subprocess.run(["patch", "-p1", "--batch", "-i", temp_path], cwd=repo_path, capture_output=True, text=True)
        if patch_process.returncode == 0: return True, "Diff applied successfully via patch fallback."
        errors.append(f"patch -p1 error: {patch_process.stderr.strip()}")

        patch_process_p0 = subprocess.run(["patch", "-p0", "--batch", "-i", temp_path], cwd=repo_path, capture_output=True, text=True)
        if patch_process_p0.returncode == 0: return True, "Diff applied successfully via patch fallback -p0."
        errors.append(f"patch -p0 error: {patch_process_p0.stderr.strip()}")

        return False, "Failed to apply diff:\n" + "\n".join(errors)
    finally:
        os.remove(temp_path)

def _extract_unified_diff(text: str) -> str:
    diff_blocks = []
    for language, block in re.findall(r"```(\w*)\n(.*?)```", text, re.DOTALL):
        if language.lower() in {"diff", "patch"} or block.lstrip().startswith(("diff --git", "--- ")):
            diff_blocks.append(block.strip())

    if diff_blocks: return "\n\n".join(diff_blocks)

    match = re.search(r"((?:diff --git|--- [ab]/|--- \S+).*?)(?:\n\n\w|\Z)", text, re.DOTALL)
    if match: return match.group(1).strip()
    if text.lstrip().startswith(("diff --git", "--- ")): return text
    return ""
