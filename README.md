# Agentic PR Builder

An autonomous CLI tool that automatically fixes bugs in Go repositories. Give it a GitHub repository URL and an issue description, and it will clone the repository, locate the bug, write a patch, run tests, and generate a pull request summary.

---

## Quick Start

### 1. Installation
```bash
git clone https://github.com/thegirlhacker/pocketFM.git
cd pocketFM

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file in the project root:
```env
GEMINI_API_KEY="your-gemini-api-key"
# Or
OPENAI_API_KEY="your-openai-api-key"
# Or
GROQ_API_KEY="your-groq-api-key"
```

### 3. Usage

**Autonomous Mode (CLI Arguments):**
```bash
python3 main.py --repo https://github.com/gin-gonic/gin --issue "Non-standard X-Forwarded-For header content is not supported"
```

**Interactive Mode:**
```bash
python3 main.py
# The CLI will prompt you to enter the repo URL and issue text.
```

---

## System Architecture

1. **AST-Like Search Funnel**: Extracts keywords from the issue, greps the repository, and ranks matched Go files using Go symbol/type matching and keyword density.
2. **Planner Agent**: Proposes an investigation and fix strategy.
3. **Coder Agent**: Writes a `git apply`-compatible unified patch.
4. **Self-Healing Validation Loop**: Applies the patch and validates via `go build` and `go test` (auto-downloads a Go toolchain if not installed). If errors occur, the compiler log is fed back to the Coder for automatic correction (up to 3 retries).
5. **PR Generator**: Summarizes changes into a conventional commit format and PR body.

---

## File Structure

- `main.py` - CLI entry point.
- `core/` - Orchestrator and agent system prompt templates.
- `tools/` - Internals for search funnel, diff application, and Go test runners.
