# Agentic PR Builder

An autonomous AI agent platform that resolves issues in open-source Go projects. It automatically clones the target repository, uses a highly optimized 3-step search funnel to identify relevant code, reasons about the issue, plans a fix, applies the diff, validates it via `go build` and `go test`, and generates a Pull Request summary.

## Core Architecture

* **The Funnel:** Efficiently maps issues to files without blowing up the context window.
  - Step 1 (Wide Net): Fast grep to find all keyword mentions.
  - Step 2 (Sorter): Ranks files via Match Density and Go Symbol (func/type) hits.
  - Step 3 (Detective): The Planner LLM reads the top candidate and formulates a plan.
* **The Coder:** A dedicated LLM that strictly generates accurate `git apply` compatible diffs based on the plan.
* **The Validator:** Automatically applies the diff and runs `go build ./...` and `go test ./...` in the cloned repo.
* **The PR Generator:** Synthesizes the initial issue and the successful diff into a ready-to-use Pull Request Markdown summary.
* **Rich UI:** Beautiful, color-coded terminal updates providing transparency into the agent's "thoughts" and actions.

## Setup Instructions

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
      ```

3. **Run the Agent:**
    ```bash
    python main.py
    ```
    The CLI will interactively ask you to:
    1. Paste the URL of the GitHub repository (e.g., `https://github.com/gin-gonic/gin`).
    2. Paste the exact Issue description.

## Target Projects
This tool is specifically tuned and tested for major open-source Go projects:
* [gin-gonic/gin](https://github.com/gin-gonic/gin)
* [spf13/cobra](https://github.com/spf13/cobra)
* [go-playground/validator](https://github.com/go-playground/validator)
* [golangci/golangci-lint](https://github.com/golangci/golangci-lint)
