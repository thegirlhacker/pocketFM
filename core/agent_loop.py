"""
agent_loop.py
~~~~~~~~~~~~~
Houses the generic ReAct (Reason + Act) loop that both the Planner and Coder
agents share, plus the tool-call parser and the rate-limit-aware API wrapper.

Keeping these here means orchestrator.py only needs to know *what* to run
(the 4-stage pipeline) and not *how* the loop works internally.
"""

import ast
import inspect
import json
import logging
import re
import time

import openai
from openai import OpenAI
from rich.console import Console

from tools.registry.tool_registry import ToolRegistry
from core.file_utils import MAX_CONTEXT

console = Console()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate-limit-safe API wrapper
# ---------------------------------------------------------------------------

def safe_api_call(
    client: OpenAI,
    model: str,
    messages: list,
    temperature: float = 0.2,
    max_retries: int = 10,
    initial_delay: float = 5.0,
) -> object:
    """
    Wraps client.chat.completions.create() in an exponential-backoff retry
    loop.  Only rate-limit / connection / server errors are retried; all other
    exceptions propagate immediately.

    Returns the raw OpenAI response object on success.
    Raises the last exception if all retries are exhausted.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            return response

        except (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.InternalServerError,
        ) as exc:
            if attempt == max_retries - 1:
                console.print(
                    f"[bold red]❌ Exhausted API retries after {max_retries} attempts: {exc}[/bold red]"
                )
                raise

            # Some providers explicitly request an 18-second wait in the error body.
            wait_time = delay
            if "18s" in str(exc) or "18." in str(exc):
                wait_time = max(wait_time, 20)

            console.print(
                f"[yellow]⏳ Transient API error ({type(exc).__name__}). "
                f"Retrying in {wait_time:.0f}s... (attempt {attempt + 1}/{max_retries})[/yellow]"
            )
            time.sleep(wait_time)
            delay *= 1.5  # Exponential backoff

        except Exception as exc:
            console.print(f"[bold red]❌ Unexpected API error: {exc}[/bold red]")
            raise


# ---------------------------------------------------------------------------
# Tool-call parser
# ---------------------------------------------------------------------------

def parse_tool_call(text: str, tool_registry: ToolRegistry):
    """
    Extracts a tool name and its arguments from free-text LLM output.

    The model is expected to emit one of these patterns:
        TOOL_CALL: name {"key": "value"}
        TOOL_CALL: name({"key": "value"})
        TOOL_CALL: name("value1", "value2")

    Returns (tool_name: str | None, args: dict | None).
    Returns (None, None) if no tool call is found.

    Parse order (most to least reliable):
      1. JSON object  - handles quoted strings correctly (the safe path)
      2. ast.literal_eval - handles Python-style dicts
      3. Key-value regex  - simple "key: value" or "key=value" pairs
      4. Positional args  - maps positional quoted/numeric literals to param names

    NOTE: For tool arguments that contain raw code snippets (edit_file's
    old_snippet / new_snippet), JSON parsing (pattern 1) is the only reliable
    option. The fallbacks handle simpler tools like grep(keyword) or tree(depth).
    """

    # ---- locate the TOOL_CALL marker -----------------------------------------
    # Pattern A: TOOL_CALL: name({...}) or TOOL_CALL: name("arg")
    match = re.search(
        r'TOOL_CALL:\s*([a-zA-Z_]\w*)\s*\((.*?)\)\s*$',
        text,
        re.DOTALL | re.MULTILINE,
    )
    if match:
        tool_name = match.group(1)
        args_str = match.group(2).strip()
    else:
        # Pattern B: TOOL_CALL: name {...}  (no parentheses)
        match = re.search(
            r'TOOL_CALL:\s*([a-zA-Z_]\w*)\s*(\{.*?\})\s*$',
            text,
            re.DOTALL | re.MULTILINE,
        )
        if match:
            tool_name = match.group(1)
            args_str = match.group(2).strip()
        else:
            return None, None

    if not args_str:
        return tool_name, {}

    # ---- attempt 1: JSON -------------------------------------------------------
    candidate = args_str
    if candidate.startswith("{") and candidate.endswith("}"):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return tool_name, parsed
        except json.JSONDecodeError:
            pass

    # ---- attempt 2: ast.literal_eval -------------------------------------------
    try:
        parsed = ast.literal_eval(candidate if candidate.startswith("{") else f"{{{candidate}}}")
        if isinstance(parsed, dict):
            return tool_name, parsed
    except Exception:
        pass

    # Strip surrounding braces for the remaining strategies
    inner = candidate
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1].strip()

    # ---- attempt 3: key-value regex --------------------------------------------
    kv_pattern = re.compile(
        r'(?:["\']?([a-zA-Z_]\w*)["\']?)'
        r'\s*[:=]\s*'
        r'(?:'
        r'(["\'])(.*?)\2'
        r'|([0-9]+(?:\.[0-9]+)?)'
        r'|(True|False|None|nil)'
        r')',
        re.DOTALL,
    )
    args_dict: dict = {}
    for m in kv_pattern.finditer(inner):
        key = m.group(1)
        if m.group(2):      # quoted string
            val = m.group(3)
        elif m.group(4):    # number
            raw = m.group(4)
            val = float(raw) if "." in raw else int(raw)
        else:               # literal
            raw = m.group(5)
            val = {"True": True, "False": False, "None": None, "nil": None}[raw]
        args_dict[key] = val

    if args_dict:
        return tool_name, args_dict

    # ---- attempt 4: positional quoted/numeric args -----------------------------
    pos_pattern = re.compile(
        r'(?:(["\'])(.*?)\1|([0-9]+(?:\.[0-9]+)?)|(True|False|None|nil))',
        re.DOTALL,
    )
    pos_args = []
    for m in pos_pattern.finditer(inner):
        if m.group(1):      # quoted string
            pos_args.append(m.group(2))
        elif m.group(3):    # number
            raw = m.group(3)
            pos_args.append(float(raw) if "." in raw else int(raw))
        else:               # literal
            raw = m.group(4)
            pos_args.append({"True": True, "False": False, "None": None, "nil": None}[raw])

    if pos_args:
        tool_func = tool_registry.get_tool(tool_name)
        if tool_func:
            params = list(inspect.signature(tool_func).parameters.keys())
            mapped = {params[i]: v for i, v in enumerate(pos_args) if i < len(params)}
            if mapped:
                return tool_name, mapped

    return tool_name, {}


# ---------------------------------------------------------------------------
# Generic ReAct loop
# ---------------------------------------------------------------------------

def run_agent_loop(
    client: OpenAI,
    model: str,
    messages: list,
    tool_registry: ToolRegistry,
    max_steps: int,
    stop_word: str,
) -> str | None:
    """
    Runs the Reason -> Act -> Observe loop until either:
      - The model emits ``stop_word`` at the start of a line -> returns payload after it.
      - The model emits ``PLAN_REJECTED:``                   -> returns the full rejection string.
      - ``max_steps`` are exhausted                          -> returns None.

    Args:
        client:        Authenticated OpenAI client.
        model:         Model identifier string.
        messages:      Conversation so far (mutated in place - caller owns it).
        tool_registry: Registry of callable tools the agent may invoke.
        max_steps:     Hard cap on loop iterations.
        stop_word:     Token the model must emit to signal completion
                       (e.g. "PLAN_COMPLETE:" or "FINAL_FIX:").

    The stop_word check is line-anchored (startswith per line) to prevent false
    positives when the model mentions the stop word inside its reasoning text.
    """
    for step in range(1, max_steps + 1):

        # --- Context-window guard (anti-413 for large histories) ---
        max_history = 40 if "gemini" in model else 10
        if len(messages) > max_history:
            # Keep system message + first user message, then the latest turns
            messages[:] = messages[:2] + messages[-(max_history - 2):]

        try:
            response = safe_api_call(client, model, messages, temperature=0.2)
        except Exception:
            return None

        reply = response.choices[0].message.content
        if reply is None:
            console.print(
                "[bold red]⚠️  Received empty/None content from model response.[/bold red]"
            )
            console.print(f"[dim]Response details: {response}[/dim]")
            return None

        messages.append({"role": "assistant", "content": reply})

        # --- Check for stop conditions (line-anchored to avoid false positives) ---
        for line in reply.splitlines():
            stripped = line.strip()
            if stripped.startswith(stop_word):
                # Return everything after the stop word (may span multiple lines)
                payload_start = reply.index(stripped) + len(stop_word)
                return reply[payload_start:].strip()
            if stripped.startswith("PLAN_REJECTED:"):
                return "PLAN_REJECTED:" + reply.split("PLAN_REJECTED:")[-1]

        # --- Tool dispatch ---
        tool_name, tool_args = parse_tool_call(reply, tool_registry)

        if tool_name:
            console.print(f"[dim]   ⚙️  Calling Tool: {tool_name} {tool_args}[/dim]")
            tool_result = tool_registry.execute_tool(tool_name, tool_args or {})

            # Truncate massive tool output to keep context manageable
            if len(tool_result) > MAX_CONTEXT:
                tool_result = (
                    tool_result[:MAX_CONTEXT]
                    + "\n... [TRUNCATED. Please use read_file with 'start_line' and 'end_line' to read the required section.]"
                )

            messages.append({"role": "user", "content": f"OBSERVATION:\n{tool_result}"})
        else:
            # Nudge the model if it emitted neither a tool call nor a stop word
            messages.append(
                {
                    "role": "user",
                    "content": f"Please call a tool or output {stop_word}.",
                }
            )

    return None  # Loop exhausted without success
