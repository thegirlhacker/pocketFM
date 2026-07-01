# Agentic PR Builder

An autonomous CLI tool designed to locate, fix, and validate bugs in Go repositories. Give it a repository URL and a bug report, and the agent will localize the relevant files, draft a patch, validate the fix using local tests (or auto-download a Go toolchain if missing), and generate a detailed pull request summary.

## Core Features

- **AST-Like Search Funnel**: Before calling any LLM, the tool runs a keyword extraction step on the issue, performs a codebase-wide grep, and scores files using Go symbol matching (functions/types/structs) combined with match density to find the best candidate files.
- **Two-Agent ReAct Workflow**:
  - **Planner**: Investigates the codebase using search tools (`tree`, `grep`, `read_file`), localizes the issue, and compiles a strategy.
  - **Coder**: Takes the plan and generates a `git apply`-compatible unified diff.
- **Self-Healing Validation Loop**: Automatically runs `go build` and `go test` on modified packages. If compiler or test errors occur, it feeds the compile/test error logs and the surrounding context of the failing files back to the Coder for up to 3 automatic retries.
- **Context Management**: Avoids token bloat and `413 Payload Too Large` errors by keeping system instructions compact, capping read operations to 15KB, and managing short-term history memory (sliding window keeping only the system context + the latest 8 messages).
- **Environment Autodetection**: Automatically detects your API key type and base URL. It supports OpenAI, Gemini, Groq, and GitHub Models. If `go` is not installed on the system, it automatically pulls a sandboxed Go toolchain to validate changes.

---

## Architecture Flow

```
[Issue Text] ──> Keyword Extraction ──> Global Grep Net ──> Go Symbol Ranking
                                                                   │
                                                                   ▼
[PR Summary] <── PR Generator <── [Passed tests] <── Coder & Validation Loop (up to 3x)
```

---

## Codebase Tour

- `main.py`: Entry point for the CLI. Manages repo cloning, environment variables, base URL mapping, and runs the main loop.
- `core/`:
  - `orchestrator.py`: Implements `AgentOrchestrator` which coordinates the Planner, Coder, and PR Generator agents.
  - `prompts/`: Standardized system templates for the agents.
- `tools/`:
  - `search/`: Contains `grep_tool.py` for keyword searches and `tree_mapper.py` for directory exploration.
  - `editor/`: `file_reader.py` parses symbols/functions and handles scoring. `diff_applier.py` handles parsing code diffs and applying patches using `git apply` or `patch` (with `-p0` and `-p1` fallbacks).
  - `validator/`: `go_tester.py` compiles directories and runs unit tests. It also manages downloading a temporary Go binary if local Go is unavailable.

---

## Setup & Configuration

### Prerequisites
- Python 3.12 or higher
- Git

### Installation

1. Clone the repository and navigate to its root:
   ```bash
   git clone https://github.com/thegirlhacker/pocketFM.git
   cd pocketFM
   ```

2. Create a virtual environment and install the required dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the root directory:
   ```env
   # Set the API key for your preferred provider
   GEMINI_API_KEY="your-gemini-api-key"
   # OR
   OPENAI_API_KEY="your-openai-api-key"
   # OR
   GROQ_API_KEY="your-groq-api-key"

   # Optional base URL override (detected automatically based on key structure if omitted)
   # OPENAI_BASE_URL="https://models.inference.ai.azure.com"
   ```

---

## Usage

Run the tool using:
```bash
python3 main.py
```

### Flow of Execution:
1. **GitHub URL**: The prompt will ask you to paste the URL of the Go repository.
2. **Issue Description**: Paste the issue description or error report (press Enter twice to submit).
3. **Execution**: The tool will clone the target repository, run search scoring, execute the Planner and Coder loops, validate the fix by compiling and running tests, and output a conventional PR description along with the final diff.
4. **Cleanup**: Cloned repository files are cleaned up upon successful completion or interruption.
