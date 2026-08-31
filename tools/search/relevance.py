import re
from collections import defaultdict
from tools.search.grep_tool import collect_grep_matches, _match_weight

STOP_WORDS = {
    "about", "after", "also", "before", "being", "cannot", "could",
    "error", "expected", "fails", "from", "have", "issue", "should",
    "that", "this", "when", "with",
}

def extract_issue_keywords(issue_description: str, max_keywords: int = 12) -> list[str]:
    candidates = []
    candidates.extend(re.findall(r"`([^`]+)`", issue_description))
    candidates.extend(re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", issue_description))
    candidates.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", issue_description))

    seen, keywords = set(), []
    for raw in candidates:
        word = raw.strip()
        if not word: continue
        if word.endswith(".go"): word = word[:-3]
        word = word.split("/")[-1].split("\\")[-1].split("(")[0].split(".")[-1].strip()
        
        normalized = word.lower()
        if normalized in STOP_WORDS or normalized in seen or (len(word) < 4 and "_" not in word):
            continue
            
        seen.add(normalized)
        keywords.append(word)
        if len(keywords) >= max_keywords: break

    return keywords

def find_relevant_files(repo_path: str, issue_description: str, limit: int = 5) -> dict[str, list[dict]]:
    keywords = extract_issue_keywords(issue_description)
    if not keywords: return {}

    matches_by_file = defaultdict(list)
    for keyword in keywords:
        for match in collect_grep_matches(repo_path, keyword, go_only=True):
            matches_by_file[match.file_path].append(match)

    def _score(matches):
        return (any(_match_weight(m.line_text) == 5 for m in matches), sum(_match_weight(m.line_text) for m in matches))

    top_files = sorted(matches_by_file, key=lambda fp: _score(matches_by_file[fp]), reverse=True)[:limit]
    
    result = {}
    for fp in top_files:
        seen = set()
        result[fp] = []
        for m in sorted(matches_by_file[fp], key=lambda m: (-_match_weight(m.line_text), m.line_number)):
            if m.line_number not in seen:
                seen.add(m.line_number)
                result[fp].append({"line": m.line_number, "text": m.line_text})
                
    return result
