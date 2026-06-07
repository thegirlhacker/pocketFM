import re
import textwrap
import subprocess
import os
import tempfile


def revert_repo(repo_path: str):
    """Hard resets the repository to discard any applied diffs during retries."""
    subprocess.run(["git", "reset", "--hard"], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, capture_output=True)


def extract_modified_files(diff_text: str) -> list[str]:
    """Parses the diff to find which files are being modified."""
    files = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
    return files


def apply_git_diff(repo_path: str, final_fix: str) -> tuple[bool, str]:
    """Extracts the diff from the LLM output and applies it to the repository."""
    cleaned_fix = (final_fix or "").strip()
    unified_diff = _extract_unified_diff(cleaned_fix)
    
    if not unified_diff:
        return False, "No valid unified diff found in the model's output."

    # Write diff to a temporary file
    fd, temp_path = tempfile.mkstemp(suffix=".diff")
    with os.fdopen(fd, 'w') as f:
        f.write(unified_diff + "\n")

    try:
        # Use git apply
        process = subprocess.run(
            ["git", "apply", "--ignore-space-change", "--ignore-whitespace", temp_path],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if process.returncode == 0:
            return True, "Diff applied successfully."
        else:
            # Fallback to patch utility if git apply is too strict
            patch_process = subprocess.run(
                ["patch", "-p1", "-i", temp_path],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            if patch_process.returncode == 0:
                return True, "Diff applied successfully via patch fallback."
            return False, f"Failed to apply diff:\nGit apply error: {process.stderr}\nPatch fallback error: {patch_process.stderr}"
    finally:
        os.remove(temp_path)


def format_terminal_edits(final_fix: str | None) -> str:
    """Format the coder output as terminal-ready proposed edits."""
    cleaned_fix = (final_fix or "").strip()
    if not cleaned_fix:
        return "No code changes were produced."

    unified_diff = _extract_unified_diff(cleaned_fix)
    if unified_diff:
        body = unified_diff
    else:
        body = _normalize_file_blocks(cleaned_fix)

    return "\n".join(
        [
            "",
            "=" * 72,
            "PROPOSED CODE CHANGES",
            "=" * 72,
            body.strip(),
            "=" * 72,
        ]
    )


def _extract_unified_diff(text: str) -> str:
    diff_blocks = []
    for language, block in re.findall(r"```(\w*)\n(.*?)```", text, re.DOTALL):
        if language.lower() in {"diff", "patch"} or block.lstrip().startswith(("diff --git", "--- ")):
            diff_blocks.append(block.strip())

    if diff_blocks:
        return "\n\n".join(diff_blocks)

    if text.lstrip().startswith(("diff --git", "--- ")):
        return text

    return ""


def _normalize_file_blocks(text: str) -> str:
    code_blocks = re.findall(r"```(?:go)?\n(.*?)```", text, re.DOTALL)
    if not code_blocks:
        return textwrap.dedent(text).strip()

    intro = text.split("```", 1)[0].strip()
    sections = []
    if intro:
        sections.append(intro)

    for block in code_blocks:
        sections.append("```go\n" + block.strip() + "\n```")

    return "\n\n".join(sections)
