import json
import os
import time
import logging
import subprocess

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from tools.search.grep_tool import grep_search
from tools.search.tree_mapper import get_repo_structure
from tools.editor.diff_applier import (
    apply_git_diff,
    revert_repo,
    extract_modified_files,
    edit_file_tool,
    _extract_unified_diff,
)
from tools.editor.file_reader import (
    find_relevant_files,
    read_file_with_line_numbers,
    read_function as _read_function,
)
from tools.validator.go_tester import run_go_validation
from core.file_utils import load_prompt, MAX_CONTEXT
from tools.registry.tool_registry import ToolRegistry
from core.agent_loop import run_agent_loop, safe_api_call

console = Console()
logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """
    Coordinates the four-stage autonomous repair pipeline:

      Stage 1 – Planner  : investigates the issue, produces an action plan.
      Stage 2 – Coder    : writes a fix following the plan.
      Stage 3 – Validator: applies the diff, runs go build + go test, reverts on failure.
      Stage 4 – PR Gen   : writes a PR title + body for the validated change.

    The ReAct loop mechanics (parse_tool_call, safe_api_call, run_agent_loop)
    live in core/agent_loop.py so this class stays focused on pipeline logic.
    """

    MAX_RETRIES = 3   # maximum coder + validation attempts before giving up

    def __init__(
        self,
        repo_path: str,
        api_key: str,
        base_url: str = None,
        model: str = "gpt-4o",
    ):
        self.repo_path = repo_path
        self.model = model

        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)

        # Load system prompts
        self.planner_sys_prompt = load_prompt("planner_prompt")
        self.coder_sys_prompt = load_prompt("coder_prompt")
        self.pr_generator_sys_prompt = load_prompt("pr_generator_prompt")

        # Build tool registry
        self.tool_registry = ToolRegistry()
        self._register_tools()

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self):
        """Registers all tools as closures so they capture self.repo_path."""

        def grep(keyword: str) -> str:
            """Searches the codebase for a keyword. Returns file paths and occurrences."""
            return grep_search(self.repo_path, keyword)

        def tree(depth: int = 3) -> str:
            """Shows the repository folder structure up to a certain depth."""
            return get_repo_structure(self.repo_path, depth)

        def read_file(filepath: str, start_line: int = None, end_line: int = None) -> str:
            """Reads file content with exact line numbers. Use start_line and end_line to prevent truncation on large files."""
            return self._read_file(filepath, start_line, end_line)

        def read_function(filepath: str, function_name: str) -> str:
            """
            Uses Python to parse a Go file and extracts ONLY the exact function block.
            Use this to read code before attempting an edit. Do not guess the code.
            """
            return _read_function(self.repo_path, filepath, function_name)

        def edit_file(filepath: str, old_snippet: str, new_snippet: str) -> str:
            """
            Search-and-Replace Editor Tool.
            CRITICAL: 'old_snippet' MUST match the existing code in the file EXACTLY,
            including all spaces, tabs, and indentation. Do not omit any characters.
            """
            return edit_file_tool(self.repo_path, filepath, old_snippet, new_snippet)

        self.tool_registry.register("grep", grep)
        self.tool_registry.register("tree", tree)
        self.tool_registry.register("read_file", read_file)
        self.tool_registry.register("read_function", read_function)
        self.tool_registry.register("edit_file", edit_file)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_file(
        self, filepath: str, start_line: int = None, end_line: int = None
    ) -> str:
        """Read a Go file, optionally limiting to a line range."""
        content = read_file_with_line_numbers(self.repo_path, filepath)
        if content.startswith("Error"):
            return content
        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            start_idx = 0
            end_idx = len(lines)
            if start_line is not None:
                try:
                    start_idx = max(0, int(start_line) - 1)
                except (ValueError, TypeError):
                    pass
            if end_line is not None:
                try:
                    end_idx = min(len(lines), int(end_line))
                except (ValueError, TypeError):
                    pass
            return "\n".join(lines[start_idx:end_idx])
        return content

    def _get_repo_agents_context(self) -> str:
        """Looks for AGENTS.md / .github/AGENTS.md / RULES.md and injects project-specific rules."""
        candidate_paths = [
            os.path.join(self.repo_path, "AGENTS.md"),
            os.path.join(self.repo_path, ".github", "AGENTS.md"),
            os.path.join(self.repo_path, "RULES.md"),
        ]
        for path in candidate_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return (
                            f"\n\n--- REPOSITORY SPECIFIC RULES ({os.path.basename(path)}) ---\n"
                            f"{f.read().strip()}\n"
                            "-----------------------------------\n"
                        )
                except Exception as e:
                    logger.warning(f"Failed to read {path}: {e}")
        return ""

    def _build_system_prompt(self, base_prompt: str, agents_context: str) -> str:
        """Appends the live tool descriptions and any repo-specific rules to a base prompt."""
        prompt = base_prompt + "\n\nAVAILABLE TOOLS (live):\n" + self.tool_registry.get_all_tool_descriptions()
        if agents_context:
            prompt += agents_context
        return prompt

    def _get_final_diff(self, final_fix: str) -> str:
        """Returns the unified diff from the fix text, falling back to git diff."""
        diff = _extract_unified_diff(final_fix)
        if not diff:
            result = subprocess.run(
                ["git", "diff"], cwd=self.repo_path, capture_output=True, text=True
            )
            diff = result.stdout or final_fix
        return diff

    def _animate_diff(self, final_fix: str):
        """Typing-effect display of the diff before it is applied."""
        console.print("\n[bold cyan]✨ APPLYING CHANGES...[/bold cyan]")
        time.sleep(1)

        diff_text = _extract_unified_diff(final_fix)
        if not diff_text:
            diff_text = final_fix

        lines = diff_text.splitlines()
        num_lines = len(lines)
        del_add_delay = max(0.005, min(0.08, 4.0 / max(1, num_lines)))
        ctx_delay = max(0.001, min(0.02, 1.0 / max(1, num_lines)))

        for line in lines:
            if line.startswith("-") and not line.startswith("---"):
                console.print(f"[bold red]{line}[/bold red]")
                time.sleep(del_add_delay)
            elif line.startswith("+") and not line.startswith("+++"):
                console.print(f"[bold green]{line}[/bold green]")
                time.sleep(del_add_delay)
            else:
                console.print(f"[dim]{line}[/dim]")
                time.sleep(ctx_delay)

        console.print("\n[bold green]✅ Code successfully updated![/bold green]")
        time.sleep(2)

    # ------------------------------------------------------------------
    # Stage 4 – PR summary
    # ------------------------------------------------------------------

    def _generate_pr_summary(self, issue_description: str, final_fix: str) -> str:
        """Calls the PR Generator LLM to write a PR title and body."""
        console.print("\n[bold cyan]📝 STAGE 4: GENERATING PULL REQUEST SUMMARY...[/bold cyan]")
        time.sleep(1)

        diff_text = self._get_final_diff(final_fix)

        messages = [
            {"role": "system", "content": self.pr_generator_sys_prompt},
            {"role": "user", "content": f"Issue:\n{issue_description}\n\nCode Diff:\n{diff_text}"},
        ]

        try:
            response = safe_api_call(self.client, self.model, messages, temperature=0.3)
            return response.choices[0].message.content
        except Exception:
            return "Failed to generate PR summary due to an API error."

    # ------------------------------------------------------------------
    # Master pipeline
    # ------------------------------------------------------------------

    def run(self, issue_description: str):
        """Entry point – runs all four stages end-to-end."""

        # --- Pre-compute ranked file context (runs before any LLM call) ---
        ranked_files = find_relevant_files(self.repo_path, issue_description, limit=5)
        if not ranked_files:
            ranked_context = "No relevant files found from issue keywords."
        else:
            ranked_context = json.dumps(ranked_files, indent=2)
            if len(ranked_context) > MAX_CONTEXT:
                ranked_context = ranked_context[:MAX_CONTEXT] + "\n...[TRUNCATED]"

        agents_context = self._get_repo_agents_context()

        # ---- STAGE 1: PLANNER ------------------------------------------------
        time.sleep(1)
        console.print("\n[bold cyan]🧠 STAGE 1: PLANNER IS INVESTIGATING...[/bold cyan]")

        planner_messages = [
            {"role": "system", "content": self._build_system_prompt(self.planner_sys_prompt, agents_context)},
            {
                "role": "user",
                "content": (
                    f"Issue:\n{issue_description}\n\n"
                    f"Relevant files (ranked by match score, definitions first):\n{ranked_context}\n\n"
                    "Investigate the top files. Use read_file or read_function for more detail."
                ),
            },
        ]

        plan = run_agent_loop(
            client=self.client,
            model=self.model,
            messages=planner_messages,
            tool_registry=self.tool_registry,
            max_steps=15,
            stop_word="PLAN_COMPLETE:",
        )

        if not plan:
            console.print(
                "[bold red]❌ Planner failed to create a plan within step limit or due to API errors.[/bold red]"
            )
            return

        if plan.startswith("PLAN_REJECTED:"):
            reason = plan.replace("PLAN_REJECTED:", "").strip()
            console.print(
                Panel(
                    f"[bold red]Issue Rejected:[/bold red] The issue is out of scope.\n\n"
                    f"[bold white]Reason:[/bold white]\n{reason}",
                    title="Aborted",
                    border_style="red",
                )
            )
            return

        console.print(Panel(Markdown(plan), title="Action Plan", border_style="green"))
        time.sleep(1.5)

        # ---- STAGES 2 & 3: CODER + VALIDATION LOOP ---------------------------
        coder_messages = [
            {"role": "system", "content": self._build_system_prompt(self.coder_sys_prompt, agents_context)},
            {
                "role": "user",
                "content": (
                    f"Issue:\n{issue_description}\n\n"
                    f"Action Plan:\n{plan}\n\n"
                    f"Relevant files:\n{ranked_context}\n\n"
                    "Read the files you need, then output only the code edits."
                ),
            },
        ]

        MAX_RETRIES = self.MAX_RETRIES
        final_fix_to_use = None

        for attempt in range(1, MAX_RETRIES + 1):
            console.print(
                f"\n[bold cyan]👨‍💻 STAGE 2: CODER IS WRITING FIX (Attempt {attempt}/{MAX_RETRIES})...[/bold cyan]"
            )

            final_fix = run_agent_loop(
                client=self.client,
                model=self.model,
                messages=coder_messages,
                tool_registry=self.tool_registry,
                max_steps=15,
                stop_word="FINAL_FIX:",
            )

            if not final_fix:
                console.print(
                    "[bold red]❌ Coder failed to generate a fix within step limit or due to API errors.[/bold red]"
                )
                break

            # Animated diff display
            self._animate_diff(final_fix)

            console.print("\n[bold cyan]🧪 STAGE 3: VALIDATION STARTED...[/bold cyan]")

            applied, apply_msg = apply_git_diff(self.repo_path, final_fix)
            if not applied:
                console.print(f"[bold yellow]⚠️ Failed to apply diff:\n{apply_msg}[/bold yellow]")
                console.print("[dim]Reverting changes and requesting a corrected diff...[/dim]")
                revert_repo(self.repo_path)
                coder_messages.append({
                    "role": "user",
                    "content": (
                        f"Failed to apply git diff. Ensure your diff matches the source exactly.\n"
                        f"Error:\n{apply_msg}\nPlease provide a corrected FINAL_FIX."
                    ),
                })
                time.sleep(1)
                continue

            console.print("[green]✅ Diff applied successfully to local repository.[/green]")
            console.print("[dim]Running Syntax Check (Local) & Blast Radius Check (Global)...[/dim]")

            modified_files = extract_modified_files(final_fix, self.repo_path)
            valid, val_msg, failing_context = run_go_validation(self.repo_path, modified_files)

            if valid:
                console.print("[bold green]✅ Validation successful! Code compiles and tests pass.[/bold green]")
                final_fix_to_use = final_fix
                break

            else:
                console.print(
                    "[bold yellow]⚠️ Validation Failed. Reverting changes and re-prompting Coder...[/bold yellow]"
                )
                console.print(Panel(val_msg, border_style="yellow"))
                revert_repo(self.repo_path)

                feedback = f"Validation failed after applying your diff:\n{val_msg}\n"
                if failing_context:
                    if len(failing_context) > 3000:
                        failing_context = failing_context[:3000] + "\n...[TRUNCATED]"
                    feedback += f"\nBroken file context:\n{failing_context}\n"
                feedback += "Please analyze the error and provide a corrected FINAL_FIX."

                coder_messages.append({"role": "user", "content": feedback})
                time.sleep(1)

        if not final_fix_to_use:
            console.print(
                "[bold red]❌ Failed to generate a validated fix after multiple attempts.[/bold red]"
            )
            return

        # ---- STAGE 4: PR GENERATOR -------------------------------------------
        pr_summary = self._generate_pr_summary(issue_description, final_fix_to_use)
        console.print("\n")
        console.print(Panel(Markdown(pr_summary), title="Pull Request Summary", border_style="magenta"))
