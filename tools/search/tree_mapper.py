import os
import logging
from core.file_utils import get_dynamic_ignore_patterns

logger = logging.getLogger(__name__)

def get_repo_structure(repo_path: str, max_depth: int = 4) -> str:
    """Scans the repository and returns a visually formatted tree structure."""
    if not os.path.exists(repo_path):
        return f"Error: Repository path '{repo_path}' does not exist."

    try:
        max_depth = int(max_depth)
    except (ValueError, TypeError):
        max_depth = 4

    ignore_dirs, ignore_exts = get_dynamic_ignore_patterns(repo_path)
    tree_str = f"Repository Map for: {os.path.basename(os.path.abspath(repo_path))}\n"
    
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        if root == repo_path:
            level = 0
        else:
            rel_path = os.path.relpath(root, repo_path)
            level = rel_path.count(os.sep) + 1
        
        if level == max_depth:
            indent = ' ' * 4 * level
            tree_str += f"{indent}📂 {os.path.basename(root)}/ ... (use search tools to look inside)\n"
            continue 
            
        if level > max_depth:
            continue
            
        indent = ' ' * 4 * level
        if level > 0:
            tree_str += f"{indent}📂 {os.path.basename(root)}/\n"
        
        sub_indent = ' ' * 4 * (level + 1)
        for f in files:
            if any(f.endswith(ext) for ext in ignore_exts):
                continue
            tree_str += f"{sub_indent}📄 {f}\n"

    return tree_str