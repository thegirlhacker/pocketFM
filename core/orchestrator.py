import json
import re
import logging
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from tools.search.grep_tool import grep_search
from tools.search.tree_mapper import get_repo_structure
from tools.editor.diff_applier import format_terminal_edits, apply_git_diff, revert_repo, extract_modified_files
from tools.editor.file_reader import (
    format_ranked_files,
    rank_relevant_files,
    read_file_with_line_numbers,
    read_ranked_files,
)
from tools.validator.go_tester import run_go_validation
from core.file_utils import load_prompt
from tools.registry.tool_registry import ToolRegistry

console = Console()
logger = logging.getLogger(__name__)

class AgentOrchestrator:
    def __init__(self, repo_path: str, api_key: str, base_url: str = None):
        self.repo_path = repo_path
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o" 
        
        # Loading Prompts
        self.planner_sys_prompt = load_prompt("planner_prompt")
        self.coder_sys_prompt = load_prompt("coder_prompt")
        self.pr_generator_sys_prompt = load_prompt("pr_generator_prompt")
        
        # Initialize Tool Registry
        self.tool_registry = ToolRegistry()
        self._register_tools()

    def _register_tools(self):
        """Registers all available tools dynamically."""
        
        def grep(keyword: str) -> str:
            """Searches the codebase for a keyword. Returns file paths and occurrences."""
            return grep_search(self.repo_path, keyword)
            
        def tree(depth: int = 3) -> str:
            """Shows the repository folder structure up to a certain depth."""
            return get_repo_structure(self.repo_path, depth)

        def read_file(filepath: str, start_line: int = None, end_line: int = None) -> str:
            """Reads file content with exact line numbers. ALWAYS use start_line and end_line to prevent truncation on large files."""
            return self.read_file_tool(filepath, start_line, end_line)

        self.tool_registry.register("grep", grep)
        self.tool_registry.register("tree", tree)
        self.tool_registry.register("read_file", read_file)

    def _inject_tools_into_prompt(self, prompt: str) -> str:
        """Dynamically injects available tool descriptions into the system prompt."""
        tool_descriptions = self.tool_registry.get_all_tool_descriptions()
        # Replace the hardcoded tool block with the dynamic one if present
        if "AVAILABLE TOOLS:" in prompt:
             parts = prompt.split("AVAILABLE TOOLS:")
             # Find the next section (like RULES:) or the end
             end_parts = parts[1].split("RULES:", 1)
             
             new_prompt = f"{parts[0]}AVAILABLE TOOLS:\n{tool_descriptions}\n\n"
             if len(end_parts) > 1:
                 new_prompt += f"RULES:{end_parts[1]}"
             return new_prompt
             
        return prompt

    def read_file_tool(self, filepath: str, start_line: int = None, end_line: int = None) -> str:
        """Read a Go file through the editor file reader, optionally limiting to specific lines."""
        content = read_file_with_line_numbers(self.repo_path, filepath)
        if start_line is not None and end_line is not None:
            lines = content.splitlines()
            # 1-indexed to 0-indexed logic
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            return "\n".join(lines[start_idx:end_idx])
        return content

    def parse_tool_call(self, text: str):
        """Extracts tool name and arguments from the LLM's response."""
        match = re.search(r'TOOL_CALL:\s*([a-zA-Z_]+)\((.*?)\)', text, re.DOTALL)
        if match:
            try:
                return match.group(1), json.loads(match.group(2))
            except json.JSONDecodeError:
                return match.group(1), {}
        return None, None

    # --- THE CORE ReAct LOOP (Claude Pattern) ---
    def _run_agent_loop(self, messages: list, max_steps: int, stop_word: str):
        """A generic ReAct loop that works for both Planner and Coder."""
        for step in range(1, max_steps + 1):
            
            # Anti 413 Payload Too Large Logic for GitHub Models
            # We keep system, original prompt, and only the last few messages
            if len(messages) > 10:
                messages = messages[:2] + messages[-8:]
                
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2
            )
            
            reply = response.choices[0].message.content
            messages.append({"role": "assistant", "content": reply})

            # Check if agent reached its goal (PLAN_COMPLETE or FINAL_FIX)
            if stop_word in reply:
                return reply.split(stop_word)[-1].strip()

            # Otherwise, check for tool usage
            tool_name, tool_args = self.parse_tool_call(reply)
            
            if tool_name:
                console.print(f"[dim]   ⚙️ Calling Tool: {tool_name} {tool_args}[/dim]")
                
                # Use Tool Registry for execution
                tool_result = self.tool_registry.execute_tool(tool_name, tool_args)
                
                # Anti-Context-Window-Explosion logic
                if len(tool_result) > 15000:
                    tool_result = tool_result[:15000] + "\n... [TRUNCATED. The file is too large. Please use read_file with 'start_line' and 'end_line' parameters to read the required section.]"
                
                messages.append({"role": "user", "content": f"OBSERVATION:\n{tool_result}"})
            else:
                # Nudge if the LLM gets stuck
                messages.append({"role": "user", "content": f"Please call a tool or output {stop_word}."})
                
        return None # Loop exhausted without success

    def _generate_pr_summary(self, issue_description: str, final_fix: str) -> str:
        """Calls the PR Generator LLM to write a PR title and body."""
        console.print("\n[bold cyan]📝 STAGE 4: GENERATING PULL REQUEST SUMMARY...[/bold cyan]")
        messages = [
            {"role": "system", "content": self.pr_generator_sys_prompt},
            {
                "role": "user",
                "content": f"Issue:\n{issue_description}\n\nCode Diff:\n{final_fix}"
            }
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3
        )
        return response.choices[0].message.content

    # --- THE MASTER FLOW ---
    def run(self, issue_description: str):
        ranked_files = rank_relevant_files(self.repo_path, issue_description, limit=5)
        ranked_summary = format_ranked_files(ranked_files)
        ranked_context = read_ranked_files(self.repo_path, ranked_files, max_files=1)

        # Truncate context heavily for initial prompt to prevent 413s on large repos
        if len(ranked_context) > 15000:
            ranked_context = ranked_context[:15000] + "\n...[TRUNCATED: File too large. Use read_file with start_line and end_line to read the rest.]"

        # STAGE 1: PLANNER
        console.print("\n[bold cyan]🧠 STAGE 1: PLANNER IS INVESTIGATING...[/bold cyan]")
        
        dynamic_planner_prompt = self._inject_tools_into_prompt(self.planner_sys_prompt)
        
        planner_messages = [
            {"role": "system", "content": dynamic_planner_prompt},
            {
                "role": "user",
                "content": (
                    f"Issue:\n{issue_description}\n\n"
                    f"Deterministic 3-step search funnel result:\n{ranked_summary}\n\n"
                    "Use Rank 1 first. If it does not explain the bug, inspect Rank 2 "
                    "and Rank 3 before using tree exploration."
                ),
            },
        ]
        
        plan = self._run_agent_loop(planner_messages, max_steps=15, stop_word="PLAN_COMPLETE:")
        
        if not plan:
            console.print("[bold red]❌ Planner failed to create a plan within step limit.[/bold red]")
            return

        console.print(Panel(Markdown(plan), title="Action Plan", border_style="green"))

        # STAGES 2 & 3: CODER + VALIDATION LOOP
        dynamic_coder_prompt = self._inject_tools_into_prompt(self.coder_sys_prompt)
        
        coder_messages = [
            {"role": "system", "content": dynamic_coder_prompt},
            {
                "role": "user",
                "content": (
                    f"Issue:\n{issue_description}\n\n"
                    f"Action Plan:\n{plan}\n\n"
                    f"Ranked candidate files:\n{ranked_summary}\n\n"
                    f"Initial file evidence from file_reader.py:\n{ranked_context}\n\n"
                    "Read any additional ranked files you need, then output only the code edits."
                ),
            },
        ]

        MAX_RETRIES = 3
        final_fix_to_use = None

        for attempt in range(1, MAX_RETRIES + 1):
            console.print(f"\n[bold cyan]👨‍💻 STAGE 2: CODER IS WRITING FIX (Attempt {attempt}/{MAX_RETRIES})...[/bold cyan]")
            
            final_fix = self._run_agent_loop(coder_messages, max_steps=8, stop_word="FINAL_FIX:")
            
            if not final_fix:
                console.print("[bold red]❌ Coder failed to generate a fix within step limit.[/bold red]")
                break

            console.print("\n[bold cyan]🧪 STAGE 3: APPLYING FIX AND RUNNING GO VALIDATOR...[/bold cyan]")
            
            applied, apply_msg = apply_git_diff(self.repo_path, final_fix)
            if not applied:
                console.print(f"[bold yellow]⚠️ Failed to apply diff:\n{apply_msg}[/bold yellow]")
                console.print("[dim]Reverting changes and requesting a corrected diff...[/dim]")
                revert_repo(self.repo_path)
                coder_messages.append({
                    "role": "user", 
                    "content": f"Failed to apply git diff. Ensure your diff lines up exactly with the existing source code.\nError:\n{apply_msg}\nPlease try again and provide a corrected FINAL_FIX."
                })
                continue
                
            console.print("[green]✅ Diff applied successfully to local repository.[/green]")
            console.print("[dim]Running Syntax Check (Local) & Blast Radius Check (Global)...[/dim]")
            
            modified_files = extract_modified_files(final_fix)
            valid, val_msg, failing_context = run_go_validation(self.repo_path, modified_files)
            
            if valid:
                console.print("[bold green]✅ Validation successful! Code compiles and tests pass.[/bold green]")
                final_fix_to_use = final_fix
                break
            else:
                console.print(f"[bold yellow]⚠️ Validation Failed. Reverting changes and re-prompting Coder...[/bold yellow]")
                console.print(Panel(val_msg, border_style="yellow"))
                revert_repo(self.repo_path)
                
                feedback = f"Validation failed after applying your diff:\n{val_msg}\n"
                if failing_context:
                    if len(failing_context) > 3000:
                        failing_context = failing_context[:3000] + "\n...[TRUNCATED]"
                    feedback += f"\nThis change broke other files. Here is the context of the broken files:\n{failing_context}\n"
                feedback += "Please analyze the error and provide a corrected FINAL_FIX."
                
                coder_messages.append({"role": "user", "content": feedback})
                
        if not final_fix_to_use:
            console.print("[bold red]❌ Failed to generate a validated fix after multiple attempts.[/bold red]")
            return

        # STAGE 4: PR GENERATOR
        pr_summary = self._generate_pr_summary(issue_description, final_fix_to_use)
        
        # Display Final Outputs
        console.print(format_terminal_edits(final_fix_to_use))
        console.print("\n")
        console.print(Panel(Markdown(pr_summary), title="Pull Request Summary", border_style="magenta"))
