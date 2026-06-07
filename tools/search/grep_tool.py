import os
import collections
from dataclasses import dataclass
from core.file_utils import get_dynamic_ignore_patterns


@dataclass(frozen=True)
class GrepMatch:
    file_path: str
    line_number: int
    line_text: str
    keyword: str


def collect_grep_matches(repo_path: str, keyword: str, go_only: bool = True) -> list[GrepMatch]:
    """Return structured grep matches for one keyword."""
    if not keyword or not os.path.exists(repo_path):
        return []

    ignore_dirs, ignore_exts = get_dynamic_ignore_patterns(repo_path)
    matches: list[GrepMatch] = []
    normalized_keyword = keyword.lower()

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for file in files:
            if go_only and not file.endswith(".go"):
                continue
            if any(file.endswith(ext) for ext in ignore_exts):
                continue

            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line_num, line_content in enumerate(f, 1):
                        if normalized_keyword in line_content.lower():
                            rel_path = os.path.relpath(file_path, repo_path)
                            matches.append(
                                GrepMatch(
                                    file_path=rel_path,
                                    line_number=line_num,
                                    line_text=line_content.strip(),
                                    keyword=keyword,
                                )
                            )
            except (OSError, UnicodeDecodeError):
                continue

    return matches


def grep_search(repo_path: str, keyword: str) -> str:
    """
    Highly efficient search tool. If matches are < 30, shows exact lines.
    If matches are > 30, shows a summary of which files contain the keyword.
    """
    if not os.path.exists(repo_path):
        return f"Error: Path '{repo_path}' does not exist."

    matches_data = collect_grep_matches(repo_path, keyword)

    if not matches_data:
        return f"No matches found for keyword: '{keyword}'."
        
    MAX_MATCHES = 30
    if len(matches_data) <= MAX_MATCHES:
        return "\n".join(
            [
                f"{match.file_path} (Line {match.line_number}): {match.line_text}"
                for match in matches_data
            ]
        )
    else:
        file_counts = collections.Counter([match.file_path for match in matches_data])
        summary = f"Found {len(matches_data)} matches. Showing top files:\n\n"
        for file_path, count in file_counts.most_common(15):
            summary += f"{file_path} ({count} occurrences)\n"
        summary += "\nHint: Use read_file to inspect a specific file from this list."
        return summary
