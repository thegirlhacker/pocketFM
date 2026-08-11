import os
import re
import collections
from dataclasses import dataclass
from core.file_utils import get_dynamic_ignore_patterns


@dataclass(frozen=True)
class GrepMatch:
    file_path: str
    line_number: int
    line_text: str
    keyword: str


def _match_weight(line_text: str) -> int:
    """
    Symbol definitions are much stronger relevance signals than plain usage sites.
    A function/type definition scores 5x; var/const declarations score 2x; everything else 1x.
    """
    stripped = line_text.strip()
    if stripped.startswith(("func ", "type ", "func(")):
        return 5
    if stripped.startswith(("var ", "const ")):
        return 2
    return 1


def collect_grep_matches(repo_path: str, keyword: str, go_only: bool = True) -> list[GrepMatch]:
    """Return structured grep matches for one keyword using word-boundary matching."""
    if not keyword or not os.path.exists(repo_path):
        return []

    ignore_dirs, ignore_exts = get_dynamic_ignore_patterns(repo_path)
    matches: list[GrepMatch] = []

    # Word-boundary pattern avoids "Add" matching "Address", "padding", etc.
    pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)

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
                        if pattern.search(line_content):
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
    Highly efficient search tool.
    - If matches <= 30: shows exact lines, with symbol definitions surfaced first.
    - If matches > 30: shows a relevance-weighted summary of top files.
    """
    if not os.path.exists(repo_path):
        return f"Error: Path '{repo_path}' does not exist."

    matches_data = collect_grep_matches(repo_path, keyword)

    if not matches_data:
        return f"No matches found for keyword: '{keyword}'."

    MAX_MATCHES = 30
    if len(matches_data) <= MAX_MATCHES:
        # Surface definitions (func/type/var) before plain usage sites
        ordered = sorted(matches_data, key=lambda m: -_match_weight(m.line_text))
        return "\n".join(
            f"{m.file_path} (Line {m.line_number}): {m.line_text}"
            for m in ordered
        )
    else:
        # Weighted file scoring: a file with definition hits ranks above one with log-string hits
        file_scores: collections.Counter = collections.Counter()
        file_counts: collections.Counter = collections.Counter()
        for m in matches_data:
            file_scores[m.file_path] += _match_weight(m.line_text)
            file_counts[m.file_path] += 1

        summary = f"Found {len(matches_data)} matches. Showing top files by relevance:\n\n"
        for file_path, score in file_scores.most_common(15):
            summary += f"{file_path} ({file_counts[file_path]} occurrences, relevance score {score})\n"
        summary += "\nHint: Use read_file to inspect a specific file from this list."
        return summary
