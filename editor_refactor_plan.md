## Goal Description
The `tools/editor` folder currently mixes file editing/reading logic with unrelated search capabilities and git repository management. The codebase has "big and unnecessary" code in files like `file_reader.py` (which contains search relevance logic) and `diff_applier.py` (which contains a simple string replacement tool alongside complex git patch fallbacks).

This plan proposes cleaning up the `editor` folder by moving unrelated logic out, separating the tool capabilities, and adding missing file operations (like creating/deleting files and line-range editing) to improve the LLM's editing capabilities.

## User Review Required
> [!WARNING]
> This refactor will require updating imports in `core/orchestrator.py` and `tools/editor/file_reader.py`. Are you okay with moving the git/diff operations out of the `editor` folder entirely into a new `tools/git` folder, or would you prefer keeping them in `editor/diff_applier.py`?

## Proposed Changes

### 1. Extract Search & Relevance Logic
The `file_reader.py` file currently contains issue keyword extraction and file ranking logic, which uses `grep_tool`. This has nothing to do with file reading and should be in the `search` module.

#### [NEW] `tools/search/relevance.py`
We will move the following from `tools/editor/file_reader.py` to this new file:
- `STOP_WORDS` constant
- `extract_issue_keywords()`
- `find_relevant_files()`

### 2. Clean Up File Reader
#### [MODIFY] `tools/editor/file_reader.py`
- Remove all the search and keyword extraction logic mentioned above.
- Update `read_file_with_line_numbers()` to natively accept `start_line` and `end_line` parameters. This prevents reading and processing massive files into memory entirely when only a small slice is requested (currently the slicing happens in `orchestrator.py` *after* the whole file is read).

### 3. Create Dedicated File Editor Module
The `edit_file_tool` is currently misplaced inside `diff_applier.py`, and it is limited to strict string replacements. We will extract it and add missing file operations.

#### [NEW] `tools/editor/file_editor.py`
This new file will contain:
- `edit_file_tool()`: Moved from `diff_applier.py`.
- `create_file_tool(repo_path, filepath, content)`: New tool to create files.
- `delete_file_tool(repo_path, filepath)`: New tool to delete files.
- `replace_lines_tool(repo_path, filepath, start_line, end_line, new_content)`: New tool to replace a specific block of lines safely, which is often more robust than exact snippet matching.

### 4. Clean Up Diff Applier
#### [MODIFY] `tools/editor/diff_applier.py`
- Remove `edit_file_tool()`.
- (Optional, pending feedback) Rename to `tools/git/git_utils.py` and move it out of the `editor` directory entirely, since `apply_git_diff`, `revert_repo`, and `extract_modified_files` are strictly version control operations.

### 5. Update Orchestrator
#### [MODIFY] `core/orchestrator.py`
- Update imports for `find_relevant_files` (now from `tools.search.relevance`).
- Update imports for `edit_file_tool` (now from `tools.editor.file_editor`).
- Register the new `create_file`, `delete_file`, and `replace_lines` tools with the LLM via `ToolRegistry`.
- Simplify `_read_file()` wrapper since `read_file_with_line_numbers` will handle line slicing natively.

## Verification Plan

### Automated Tests
Run `python main.py` or the suite of tests (if any exist) to ensure the agent orchestrator can still boot up and register tools without import errors.

### Manual Verification
1. Review the tool registry outputs to verify the new tools (`create_file`, `replace_lines`, etc.) are exposed correctly.
2. Run a sample query through the agent loop to verify that `grep`, `read_file`, and `edit_file` all still work without crashing.
