import os
import re
from collections import defaultdict

from tools.search.grep_tool import collect_grep_matches, _match_weight


# Words that appear in every bug report but are useless for code search.
STOP_WORDS = {
    "about", "after", "also", "before", "being", "cannot", "could",
    "error", "expected", "fails", "from", "have", "issue", "should",
    "that", "this", "when", "with",
}


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def extract_issue_keywords(issue_description: str, max_keywords: int = 12) -> list[str]:
    """Pull code-like terms out of an issue description to use as grep keywords."""
    candidates: list[str] = []
    candidates.extend(re.findall(r"`([^`]+)`", issue_description))           # `backtick` words first
    candidates.extend(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", issue_description))  # CamelCase
    candidates.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", issue_description))  # long words

    seen = set()
    keywords = []
    for raw in candidates:
        word = raw.strip()
        if not word:
            continue
        # Strip file extensions and path components
        if word.endswith(".go"):
            word = word[:-3]
        if "/" in word:
            word = word.split("/")[-1]
        if "\\" in word:
            word = word.split("\\")[-1]
        # Strip trailing parens / package prefix
        word = word.split("(")[0].split(".")[-1].strip()

        normalized = word.lower()
        if normalized in STOP_WORDS or normalized in seen:
            continue
        if len(word) < 4 and "_" not in word:
            continue

        seen.add(normalized)
        keywords.append(word)
        if len(keywords) >= max_keywords:
            break

    return keywords


# ---------------------------------------------------------------------------
# File ranking — simple and flat
# ---------------------------------------------------------------------------

def find_relevant_files(
    repo_path: str,
    issue_description: str,
    limit: int = 5,
) -> dict[str, list[dict]]:
    """
    Finds the most relevant Go files for a given issue description.

    Steps:
      1. Extract keywords from the issue text.
      2. Grep every keyword across all .go files.
      3. Group matches by file, score each file by match weight sum
         (func/type definitions count 5x, var/const 2x, plain usage 1x).
      4. Return top `limit` files as a dict:

         {
           "user/user.go": [
               {"line": 3,  "text": "func AddUser(cfg *Config) error {"},
               {"line": 12, "text": "log.Printf(\"AddUser called\")"},
           ],
           "db/db.go": [
               {"line": 45, "text": "err := AddUser(config)"},
           ]
         }

    Definition lines are sorted to the top within each file.
    """
    keywords = extract_issue_keywords(issue_description)
    if not keywords:
        return {}

    # Collect all matches grouped by file
    matches_by_file: dict[str, list] = defaultdict(list)
    for keyword in keywords:
        for match in collect_grep_matches(repo_path, keyword, go_only=True):
            matches_by_file[match.file_path].append(match)

    # Score each file as a tuple: (has_any_definition, total_weight_sum)
    # Tuple comparison means a file with even one func/type definition
    # always ranks above a file with only plain usages, no matter how many.
    def _file_score(matches):
        has_definition = any(_match_weight(m.line_text) == 5 for m in matches)
        total_weight   = sum(_match_weight(m.line_text) for m in matches)
        return (has_definition, total_weight)

    # Take top N files by score
    top_files = sorted(
        matches_by_file,
        key=lambda fp: _file_score(matches_by_file[fp]),
        reverse=True,
    )[:limit]

    # Build output dict — definition lines first within each file
    result: dict[str, list[dict]] = {}
    for fp in top_files:
        sorted_matches = sorted(
            matches_by_file[fp],
            key=lambda m: (-_match_weight(m.line_text), m.line_number),
        )
        # Deduplicate lines (same line can appear from multiple keywords)
        seen_lines: set[int] = set()
        lines_out = []
        for m in sorted_matches:
            if m.line_number not in seen_lines:
                seen_lines.add(m.line_number)
                lines_out.append({"line": m.line_number, "text": m.line_text})
        result[fp] = lines_out

    return result


# ---------------------------------------------------------------------------
# File reading tools (called by the LLM during its loop)
# ---------------------------------------------------------------------------

def read_file_with_line_numbers(repo_path: str, filepath: str) -> str:
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

    return "\n".join(f"{n} | {line}" for n, line in enumerate(lines, 1))


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

    # Strip package prefix / receiver / parens from the name
    if "." in function_name:
        function_name = function_name.split(".")[-1]
    function_name = re.sub(r"[()*]", "", function_name).strip()

    func_pattern = re.compile(
        r"^\s*func\s+(?:(?:\([^)]+\)\s+)?)?" + re.escape(function_name) + r"\b(?:\s*\[[^\]]+\])?\s*\("
    )

    start_idx = next((i for i, l in enumerate(lines) if func_pattern.match(l)), -1)
    if start_idx == -1:
        return f"Error: Function '{function_name}' not found in {filepath}."

    # Walk characters counting braces, skipping strings and comments
    brace_count = 0
    in_func = False
    end_idx = len(lines) - 1
    in_block_comment = False
    in_raw_string = False

    for i in range(start_idx, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            if in_block_comment:
                if line[j:j+2] == "*/":
                    in_block_comment = False
                    j += 2
                else:
                    j += 1
                continue
            if in_raw_string:
                if line[j] == "`":
                    in_raw_string = False
                j += 1
                continue
            if line[j:j+2] == "//":
                break                          # rest of line is comment
            if line[j:j+2] == "/*":
                in_block_comment = True
                j += 2
                continue
            if line[j] == "`":
                in_raw_string = True
                j += 1
                continue
            if line[j] == '"':                 # skip regular string
                j += 1
                while j < len(line) and line[j] != '"':
                    j += 2 if line[j] == "\\" else 1
                j += 1
                continue
            if line[j] == "'":                 # skip rune literal
                j += 1
                while j < len(line) and line[j] != "'":
                    j += 2 if line[j] == "\\" else 1
                j += 1
                continue
            if line[j] == "{":
                brace_count += 1
                in_func = True
            elif line[j] == "}":
                brace_count -= 1
            j += 1

        if in_func and brace_count == 0:
            end_idx = i
            break

    snippet = "\n".join(lines[start_idx:end_idx + 1])
    return f"// Extracted from {filepath} (Lines {start_idx + 1}-{end_idx + 1})\n{snippet}"
