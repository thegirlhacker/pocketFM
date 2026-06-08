import os
import sys
import subprocess
import shutil
import logging
from dotenv import load_dotenv

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from core.orchestrator import AgentOrchestrator

# Initialize Rich Console
console = Console()

# --- 1. SETUP LOGGING ---
# Suppress the default logger to rely on Rich for main flow, but keep it for tools
logging.basicConfig(
    level=logging.WARNING, # Only show warnings/errors from background modules
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# --- 2. HELPER FUNCTIONS ---
def clone_or_get_repo(repo_url: str) -> tuple[str, bool]:
    """Clones the repository and returns the local path plus whether it was cloned."""
    repo_name = repo_url.rstrip('/').split('/')[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    local_path = os.path.join(os.getcwd(), repo_name)
    
    if os.path.exists(local_path):
        console.print(f"[yellow]ℹ️  Using existing local repository at:[/yellow] {local_path}")
        return local_path, False

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task(description=f"Cloning repository {repo_name}...", total=None)
        try:
            subprocess.run(["git", "clone", repo_url, local_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            console.print("[green]✅ Clone successful![/green]")
            return local_path, True
        except subprocess.CalledProcessError:
            console.print("[bold red]❌ Failed to clone repository. Check the URL or your internet connection.[/bold red]")
            sys.exit(1)

def ensure_go_repo(local_path: str):
    """Fail fast when the target repository is not a Go module."""
    if not os.path.exists(os.path.join(local_path, "go.mod")):
        console.print("[bold red]❌ This assignment runner supports Go repositories only. No go.mod found.[/bold red]")
        sys.exit(1)

def cleanup_repo(local_path: str):
    """Deletes the cloned repository to save disk space."""
    if os.path.exists(local_path):
        console.print(f"[dim]🧹 Cleaning up workspace. Deleting {local_path}...[/dim]")
        try:
            shutil.rmtree(local_path, ignore_errors=True)
            console.print("[green]✅ Workspace cleaned successfully[/green]")
        except Exception as e:
            console.print(f"[red]❌ Failed to clean up workspace: {e}[/red]")

# --- 3. MAIN EXECUTION LOGIC ---
def main():
    console.print(Panel.fit("[bold blue]🤖 AGENTIC PR BUILDER: AUTONOMOUS BUG FIXER[/bold blue]", border_style="blue"))
    
    # Check API Key
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        console.print("[bold red]❌ API Key is missing! Set GROQ_API_KEY in your .env file.[/bold red]")
        sys.exit(1)

    # Get User Inputs
    console.print("\n[bold cyan]🔗 STEP 1: TARGET REPOSITORY[/bold cyan]")
    repo_url = Prompt.ask("Paste GitHub URL (e.g., https://github.com/spf13/cobra)").strip()
    if not repo_url:
        console.print("[bold red]❌ Repo URL is required. Exiting.[/bold red]")
        sys.exit(1)
        
    console.print("\n[bold cyan]🐛 STEP 2: ISSUE DESCRIPTION[/bold cyan]")
    console.print("[dim]Paste the exact issue text (Press Enter twice to finish):[/dim]")
    issue_lines = []
    while True:
        line = input()
        if line == "":
            break
        issue_lines.append(line)
    issue_description = "\n".join(issue_lines)
    
    if not issue_description.strip():
        console.print("[bold red]❌ Issue description is required. Exiting.[/bold red]")
        sys.exit(1)

    local_repo_path = ""
    local_repo_was_cloned = False
    
    try:
        # Prepare Workspace
        console.print("\n[bold cyan]📦 STEP 3: PREPARING WORKSPACE[/bold cyan]")
        local_repo_path, local_repo_was_cloned = clone_or_get_repo(repo_url)
        ensure_go_repo(local_repo_path)

        # Handover to Agent
        console.print("\n[bold cyan]🧠 STEP 4: HANDING OVER TO THE AGENT[/bold cyan]")
        
        # Smart base_url detection: Use Groq default if nothing is specified.
        base_url = os.environ.get("OPENAI_BASE_URL")
        if not base_url:
            if api_key.startswith("ghp_") or api_key.startswith("github_pat_"):
                base_url = "https://models.inference.ai.azure.com"
            else:
                base_url = "https://api.groq.com/openai/v1"

        agent = AgentOrchestrator(
            repo_path=local_repo_path, 
            api_key=api_key, 
            base_url=base_url 
        )
        
        # Start the Autonomous Loop
        agent.run(issue_description)
        
    except KeyboardInterrupt:
        console.print("\n[bold yellow]🛑 Agent stopped manually by user (Ctrl+C).[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]❌ A fatal error occurred: {e}[/bold red]")
    finally:
        # STEP 5: THE CLEANUP
        if local_repo_path:
            console.print("\n[bold cyan]♻️  STEP 5: INITIATING CLEANUP[/bold cyan]")
            cleanup_repo(local_repo_path)
            
    console.print("\n[bold green]🎯 Mission Accomplished. Exiting program.[/bold green]")

if __name__ == "__main__":
    main()
