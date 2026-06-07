import os


DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "dist",
    "build",
}

DEFAULT_IGNORE_EXTS = {
    ".bin",
    ".class",
    ".exe",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".lock",
    ".log",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".svg",
    ".zip",
}


def get_dynamic_ignore_patterns(repo_path: str) -> tuple[set[str], set[str]]:
    """Return directory names and file extensions search tools should skip."""
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    ignore_exts = set(DEFAULT_IGNORE_EXTS)

    if not os.path.exists(repo_path):
        return ignore_dirs, ignore_exts

    if os.path.exists(os.path.join(repo_path, "go.mod")):
        ignore_dirs.update({"bin", "coverage", "tmp"})
        ignore_exts.update({".test", ".out"})

    return ignore_dirs, ignore_exts


def load_prompt(prompt_name: str) -> str:
    """Load a prompt from the core/prompts directory."""
    # Assuming prompts have .md extension
    if not prompt_name.endswith('.md'):
        prompt_name += '.md'
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", prompt_name)
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error loading prompt {prompt_name}: {e}"
