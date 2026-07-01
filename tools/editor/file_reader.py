import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from tools.search.grep_tool import GrepMatch, collect_grep_matches


STOP_WORDS = {
    "about",
    "after",
    "also",
    "before",
    "being",
    "cannot",
    "could",
    "error",
    "expected",
    "fails",
    "from",
    "have",
    "issue",
    "should",
    "that",
    "this",
    "when",
    "with",
}

GO_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:func\s+(?:\([^)]*\)\s*)?|type\s+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b"
)


@dataclass
class RankedFile:
    path: str
    match_count: int
    symbol_hits: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    @property
    def score(self) -> tuple[int, int]:
        return len(self.symbol_hits), self.match_count


def extract_issue_keywords(issue_description: str, max_keywords: int = 12) -> list[str]:
    """Extract code-like search terms from an issue description."""
    candidates: list[str] = []
    candidates.extend(re.findall(r"`([^`]+)`", issue_description))
    candidates.extend(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", issue_description))
    candidates.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", issue_description))

    seen = set()
    keywords = []
    for raw_candidate in candidates:
        candidate = raw_candidate.strip()
        if not candidate:
            continue

        if candidate.endswith(".go"):
            candidate = candidate[:-3]
        if "/" in candidate:
            candidate = candidate.split("/")[-1]
        if "\\" in candidate:
            candidate = candidate.split("\\")[-1]

        candidate = candidate.split("(")[0].split(".")[-1].strip()
        normalized = candidate.lower()
        if normalized in STOP_WORDS or normalized in seen:
            continue
        if len(candidate) < 4 and "_" not in candidate:
            continue

        seen.add(normalized)
        keywords.append(candidate)
        if len(keywords) >= max_keywords:
            break

    return keywords


def rank_relevant_files(
    repo_path: str,
    issue_description: str,
    limit: int = 5,
) -> list[RankedFile]:
    """Run the wide grep net and rank candidate Go files by density and symbols."""
    keywords = extract_issue_keywords(issue_description)
    if not keywords:
        return []

    matches_by_file: dict[str, list[GrepMatch]] = defaultdict(list)
    keyword_hits_by_file: dict[str, set[str]] = defaultdict(set)

    for keyword in keywords:
        for match in collect_grep_matches(repo_path, keyword, go_only=True):
            matches_by_file[match.file_path].append(match)
            keyword_hits_by_file[match.file_path].add(keyword)

    ranked_files: list[RankedFile] = []
    for file_path, matches in matches_by_file.items():
        symbol_hits = _find_symbol_hits(os.path.join(repo_path, file_path), keywords)
        examples = [
            f"Line {match.line_number}: {match.line_text}"
            for match in matches[:3]
        ]
        ranked_files.append(
            RankedFile(
                path=file_path,
                match_count=len(matches),
                symbol_hits=symbol_hits,
                keywords=sorted(keyword_hits_by_file[file_path], key=str.lower),
                examples=examples,
            )
        )

    ranked_files.sort(key=lambda item: item.score, reverse=True)
    return ranked_files[:limit]


def format_ranked_files(ranked_files: list[RankedFile]) -> str:
    if not ranked_files:
        return "No ranked Go files found from the issue keywords."

    lines = ["Ranked candidate Go files:"]
    for index, ranked_file in enumerate(ranked_files, 1):
        symbols = ", ".join(ranked_file.symbol_hits) or "none"
        keywords = ", ".join(ranked_file.keywords) or "none"
        lines.append(
            f"{index}. {ranked_file.path} "
            f"(matches={ranked_file.match_count}, symbol_hits={symbols}, keywords={keywords})"
        )
        for example in ranked_file.examples:
            lines.append(f"   {example}")

    return "\n".join(lines)


def read_file_with_line_numbers(repo_path: str, filepath: str) -> str:
    """Read a repository file and return exact line numbers for the LLM."""
    safe_path = os.path.normpath(filepath).lstrip(os.sep)
    full_path = os.path.abspath(os.path.join(repo_path, safe_path))
    repo_root = os.path.abspath(repo_path)

    if not full_path.startswith(repo_root + os.sep) and full_path != repo_root:
        return f"Error reading file: '{filepath}' escapes the repository."
    if not full_path.endswith(".go"):
        return f"Error reading file: '{filepath}' is not a Go source file."

    try:
        with open(full_path, "r", encoding="utf-8") as source_file:
            lines = source_file.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return f"Error reading file: {exc}"

    return "\n".join(f"{line_number} | {line}" for line_number, line in enumerate(lines, 1))


def read_ranked_files(
    repo_path: str,
    ranked_files: list[RankedFile],
    max_files: int = 3,
) -> str:
    """Read the highest-ranked files for the detective LLM step."""
    chunks = []
    for ranked_file in ranked_files[:max_files]:
        chunks.append(f"FILE: {ranked_file.path}\n{read_file_with_line_numbers(repo_path, ranked_file.path)}")

    return "\n\n".join(chunks)


def _find_symbol_hits(file_path: str, keywords: list[str]) -> list[str]:
    keyword_lookup = {keyword.lower() for keyword in keywords}
    symbol_hits = []

    try:
        with open(file_path, "r", encoding="utf-8") as source_file:
            for line in source_file:
                match = GO_SYMBOL_PATTERN.match(line)
                if not match:
                    continue
                symbol_name = match.group("name")
                if symbol_name.lower() in keyword_lookup:
                    symbol_hits.append(symbol_name)
    except (OSError, UnicodeDecodeError):
        return []

    return sorted(set(symbol_hits), key=str.lower)


def read_function(repo_path: str, filepath: str, function_name: str) -> str:
    """Uses basic parsing logic to extract a Go function by name."""
    safe_path = os.path.normpath(filepath).lstrip(os.sep)
    full_path = os.path.abspath(os.path.join(repo_path, safe_path))
    repo_root = os.path.abspath(repo_path)

    if not full_path.startswith(repo_root + os.sep) and full_path != repo_root:
        return f"Error: '{filepath}' escapes the repository."
    if not full_path.endswith(".go"):
        return f"Error: '{filepath}' is not a Go source file."

    try:
        with open(full_path, "r", encoding="utf-8") as source_file:
            lines = source_file.read().splitlines()
    except Exception as exc:
        return f"Error reading file: {exc}"

    # Clean up function_name if it includes package or receiver prefixes
    if "." in function_name:
        function_name = function_name.split(".")[-1]
    function_name = re.sub(r'[()*]', '', function_name).strip()

    # Match standard func Name() or func (r Receiver) Name(), including optional generic type params
    func_pattern = re.compile(r"^\s*func\s+(?:(?:\([^)]+\)\s+)?)" + re.escape(function_name) + r"\b(?:\s*\[[^\]]+\])?\s*\(")
    
    start_line_idx = -1
    for i, line in enumerate(lines):
        if func_pattern.match(line):
            start_line_idx = i
            break
    
    if start_line_idx == -1:
        return f"Error: Function '{function_name}' not found in {filepath}."

    brace_count = 0
    in_func = False
    end_line_idx = -1
    
    in_multiline_comment = False
    in_raw_string = False
    
    for i in range(start_line_idx, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            if in_multiline_comment:
                if j < len(line) - 1 and line[j] == '*' and line[j+1] == '/':
                    in_multiline_comment = False
                    j += 2
                else:
                    j += 1
                continue
                
            if in_raw_string:
                if line[j] == '`':
                    in_raw_string = False
                j += 1
                continue
                
            if j < len(line) - 1 and line[j] == '/' and line[j+1] == '/':
                break
            if j < len(line) - 1 and line[j] == '/' and line[j+1] == '*':
                in_multiline_comment = True
                j += 2
                continue
            if line[j] == '`':
                in_raw_string = True
                j += 1
                continue
            if line[j] == '"':
                j += 1
                while j < len(line) and line[j] != '"':
                    if line[j] == '\\':
                        j += 2
                    else:
                        j += 1
                j += 1
                continue
            if line[j] == '\'':
                j += 1
                while j < len(line) and line[j] != '\'':
                    if line[j] == '\\':
                        j += 2
                    else:
                        j += 1
                j += 1
                continue
                
            char = line[j]
            if char == '{':
                brace_count += 1
                in_func = True
            elif char == '}':
                brace_count -= 1
            j += 1
        
        if in_func and brace_count == 0:
            end_line_idx = i
            break
            
    if end_line_idx == -1:
        end_line_idx = len(lines) - 1

    extracted_lines = lines[start_line_idx:end_line_idx+1]
    snippet = "\n".join(extracted_lines)
    return f"// Extracted from {filepath} (Lines {start_line_idx + 1}-{end_line_idx + 1})\n{snippet}"

