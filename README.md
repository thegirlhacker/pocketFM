# Agentic PR Builder

[![Built by thegirlhacker](https://img.shields.io/badge/Built_by-thegirlhacker-blue.svg)](https://github.com/thegirlhacker)
[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An autonomous AI agent platform that resolves issues in open-source Go projects. It automatically clones the target repository, uses a highly optimized 3-step search funnel to identify relevant code, reasons about the issue, plans a fix, applies the diff, validates it via `go build` and `go test`, and generates a Pull Request summary.

## ✨ Core Innovations & Architecture

This project isn't just a simple API wrapper; it features a robust, multi-agent architecture with significant optimizations for context management and tool execution.

### 🔍 1. The Deterministic 3-Step Search Funnel
LLMs have finite context windows. Dumping an entire repository into an LLM is expensive and causes hallucinations. This system uses a highly optimized, deterministic search funnel to feed the agent exactly what it needs:
1. **Keyword Extraction:** Dynamically parses the GitHub issue to extract code-like search terms (handling backticks, PascalCase, and Snake_case) while filtering out common English stop-words.
2. **The Wide Grep Net:** Runs a global text search across the repository to find all files containing these keywords.
3. **Symbol Matching & Ranking (The Sorter):** Parses the matched files using regex (`GO_SYMBOL_PATTERN`) to find actual Go structural definitions (`func` or `type`). Files are ranked by a strict score: **(Exact Symbol Hits, Total Match Density)**. The top 5 files are fed to the Planner.

### 🧠 2. Multi-Agent LLM Pipeline (ReAct Loop)
The system divides labor into specialized roles, operating in a strict Thought -> Action -> Observation (ReAct) loop:
* **The Planner:** Reads the heavily ranked files, investigates using tools (`tree`, `grep`, `read_file`), and formulates an actionable architectural plan.
* **The Coder:** Takes the Planner's output and strictly focuses on writing an accurate, `git apply` compatible unified diff.
* **The Validator:** Applies the fix and runs localized environment tests.
* **The PR Generator:** Synthesizes the final diff and original issue into a professional Markdown Pull Request summary.

### ⚡ 3. Advanced Optimizations & Resilience
* **Context Explosion Protection:** Prevents API `413 Payload Too Large` errors via intelligent conversation history truncation (keeping the system prompt and the most recent 8 messages) and hard limits on file reads (truncating reads over 15,000 characters).
* **Robust Diff Application:** LLMs notoriously struggle with precise diff formatting. The `diff_applier.py` forces `a/` and `b/` header prefixes, extracts raw code blocks, attempts strict `git apply --ignore-space-change`, and automatically falls back to the more lenient `patch -p1` utility if git rejects it.
* **Graceful Degradation:** The Go Validator dynamically checks the host environment (`shutil.which("go")`). If the Go toolchain isn't installed, it gracefully bypasses the validation phase rather than crashing the entire pipeline.
* **Automated Rollbacks:** If the Coder generates an invalid patch, or the validation stage fails, the system automatically runs `git reset --hard` and `git clean -fd`, feeding the exact error logs back to the Coder for a self-correction retry.

### 🔌 4. Extensibility
* **Dynamic Tool Registry:** The system features a plug-and-play `ToolRegistry`. Tools like `grep_search` and `tree_mapper` are registered in Python, and their descriptions/schemas are dynamically injected into the LLM's system prompts. Adding a new capability takes 3 lines of code.
* **Model Agnostic:** Built entirely on the standard OpenAI SDK, making it seamlessly compatible with OpenAI, Azure, GitHub Models, or local models via Ollama/vLLM.

---

## 🚀 Setup Instructions

1. **Initialize the Environment:**
    ```bash
    # Create and activate virtual environment
    python -m venv venv
    source venv/bin/activate  # Or `venv\Scripts\activate` on Windows
    
    # Install dependencies
    pip install -r requirements.txt
    ```

2. **Configuration:**
    The system supports any OpenAI-compatible API (including GitHub Models, which provides free access to `gpt-4o`).
    
    * Copy the `.env` template or create a `.env` file in the root directory:
      ```env
      # Example: Using a free GitHub Personal Access Token (PAT)
      OPENAI_API_KEY="github_pat_YourTokenHere"
      # Base URL (Optional: Defaults to GitHub Models if token starts with ghp_)
      # OPENAI_BASE_URL="https://models.inference.ai.azure.com"
      ```

3. **Run the Agent:**
    ```bash
    python main.py
    ```
    The CLI will interactively ask you to:
    1. Paste the URL of the GitHub repository (e.g., `https://github.com/gin-gonic/gin`).
    2. Paste the exact Issue description.
    3. Sit back and watch it fix the issue!

## 🎯 Target Projects

This tool is specifically tuned and tested for major open-source Go projects, including but not limited to:
* [spf13/cobra](https://github.com/spf13/cobra)
* [gin-gonic/gin](https://github.com/gin-gonic/gin)
* [go-playground/validator](https://github.com/go-playground/validator)
* [golangci/golangci-lint](https://github.com/golangci/golangci-lint)

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/thegirlhacker/pocketFM/issues).
