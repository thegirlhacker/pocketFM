## Goal Description
You asked me to check the `tools/search/grep_tool.py` and `tools/search/tree_mapper.py` tools and see if this project will work end-to-end when a user provides a repo and an issue link.

The search tools (`grep_tool.py` and `tree_mapper.py`) are concise and work perfectly fine. `grep_tool` correctly filters for `.go` files by default and provides relevance-based scoring which is ideal for this agent.

However, **there is a major flaw in the project's end-to-end flow** that will prevent users from actually getting their code fixed. 

Right now, if a user provides a GitHub repo link, the script will:
1. Clone the repo to a local directory.
2. Let the AI agent fix the code and validate it.
3. Print a "PR Summary" (Title and Body) to the console.
4. **Immediately delete the local repository folder** (via the `cleanup_repo` step in `main.py`).

Because the script doesn't actually interact with the GitHub API to open a real PR, and because it deletes the cloned folder, **the fix is completely lost forever**. The user just sees a printed PR title on their terminal and gets nothing else.

Additionally, there is a minor bug in `go_tester.py` where it tries to download a Linux Go binary if it's run on a Windows machine without Go installed.

## User Review Required
> [!IMPORTANT]  
> Are you okay with disabling the automatic deletion of the repository if a fix is successfully found? I propose we leave the fixed repository on disk and tell the user where it is so they can review the code and commit it themselves.

## Proposed Changes

### `main.py`
To prevent losing the fix, we will update the main orchestration logic.
#### [MODIFY] main.py
- Update the `cleanup_repo` logic in the `finally` block. 
- If the agent successfully generated a fix (`final_fix_to_use` is not None), we will **skip** the cleanup step and print a message telling the user: *"Your fixed repository is located at: <path>. You can cd into it and push the changes!"*
- If the agent failed, we can safely clean up the repo.
- Also, we should print the actual `git diff` at the very end alongside the PR summary so the user can easily copy/paste it if they just want the patch.

### `tools/validator/go_tester.py`
To fix the toolchain download bug for Windows users.
#### [MODIFY] tools/validator/go_tester.py
- Update `get_go_binary()`: If `platform.system().lower() == "windows"`, fail gracefully and tell the user to install Go manually, instead of trying to download a Linux `.tar.gz` and crashing. (Alternatively, add Windows `.zip` extraction support, but failing gracefully is the safest and shortest route).

## Verification Plan

### Automated Tests
Run `python main.py --repo <some_repo> --issue <some_issue>` (or run a mock version of the end-to-end loop) and verify that if it succeeds, the cloned directory is left intact on the file system.

### Manual Verification
1. Ensure `main.py` skips the deletion of `local_repo_path` on success.
2. Ensure the full git patch diff is printed at the end of the run.
