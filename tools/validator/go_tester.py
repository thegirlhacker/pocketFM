import subprocess
import os
import re
import shutil
import platform
import urllib.request
import tarfile
from tools.editor.file_reader import read_file_with_line_numbers

def extract_failing_files(output: str) -> set[str]:
    """Extracts filenames from Go compiler or test errors (e.g., utils.go:12:3)."""
    pattern = r"(?m)^([a-zA-Z0-9_\-\./\\]+\.go):\d+:"
    return set(re.findall(pattern, output))

def get_failing_files_context(repo_path: str, files: set[str]) -> str:
    """Reads the contents of the files that broke so the LLM can fix them."""
    context = ""
    for f in files:
        if not os.path.exists(os.path.join(repo_path, f)):
            continue
        context += f"\n--- {f} ---\n"
        file_content = read_file_with_line_numbers(repo_path, f)
        if len(file_content) > 15000:
            file_content = file_content[:15000] + "\n...[TRUNCATED]..."
        context += file_content
    return context

def get_go_binary(repo_path: str) -> str:
    """Finds the global Go binary or dynamically pulls the required version based on go.mod."""
    if shutil.which("go"):
        return "go"

    local_go_dir = os.path.join(repo_path, ".go_toolchain")
    local_go_bin = os.path.join(local_go_dir, "go", "bin", "go")
    if os.path.exists(local_go_bin):
        return local_go_bin

    # Determine version from go.mod
    version = "1.22.4" # fallback version
    go_mod_path = os.path.join(repo_path, "go.mod")
    if os.path.exists(go_mod_path):
        try:
            with open(go_mod_path, 'r') as f:
                for line in f:
                    if line.startswith("go "):
                        v = line.strip().split()[1]
                        if len(v.split('.')) == 2:
                            v += ".0" # e.g., 1.21 -> 1.21.0
                        version = v
                        break
        except Exception:
            pass

    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "amd64" if machine in ["x86_64", "amd64"] else "arm64"
    if system not in ["linux", "darwin"]:
        system = "linux" # default fallback
    
    url = f"https://go.dev/dl/go{version}.{system}-{arch}.tar.gz"
    
    print(f"\n[dim]Downloading Go toolchain {version} from {url}...[/dim]")
    os.makedirs(local_go_dir, exist_ok=True)
    tar_path = os.path.join(local_go_dir, "go.tar.gz")
    
    try:
        urllib.request.urlretrieve(url, tar_path)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=local_go_dir)
        os.remove(tar_path)
    except Exception as e:
        print(f"Failed to pull Go toolchain: {e}")
        return ""
        
    return local_go_bin if os.path.exists(local_go_bin) else ""


def run_go_validation(repo_path: str, modified_files: list[str]) -> tuple[bool, str, str]:
    """
    Implements the 'Medium Way' Validation Flow.
    """
    go_bin = get_go_binary(repo_path)
    if not go_bin:
        return True, "Validation skipped: 'go' executable could not be found or downloaded.", ""

    if not os.path.exists(os.path.join(repo_path, "go.mod")):
        return False, "Not a Go repository (no go.mod found).", ""

    # --- STEP 1: The Quick Syntax Check (Local Test) ---
    target_dirs = set()
    for f in modified_files:
        d = os.path.dirname(f)
        target_dirs.add(f"./{d}" if d else ".")
    
    if not target_dirs:
        target_dirs = ["./..."]

    for target in target_dirs:
        local_test = subprocess.run(
            [go_bin, "test", target],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        if local_test.returncode != 0:
            err_out = local_test.stdout + "\n" + local_test.stderr
            return False, f"STEP 1 Local Test Failed for package {target}:\n{err_out}", ""

    # --- STEP 2: The Blast Radius Check (Global Build + Test) ---
    build_process = subprocess.run(
        [go_bin, "build", "./..."],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    if build_process.returncode != 0:
        err_out = build_process.stderr
        failing_files = extract_failing_files(err_out)
        context = get_failing_files_context(repo_path, failing_files)
        return False, f"STEP 2 Global Build Failed (Blast Radius Check):\n{err_out}", context

    test_process = subprocess.run(
        [go_bin, "test", "./..."],
        cwd=repo_path,
        capture_output=True,
        text=True
    )
    if test_process.returncode != 0:
        err_out = test_process.stdout + "\n" + test_process.stderr
        failing_files = extract_failing_files(err_out)
        context = get_failing_files_context(repo_path, failing_files)
        return False, f"STEP 2 Global Test Failed (Blast Radius Check):\n{err_out}", context

    # --- STEP 3: Success! ---
    return True, "Validation successful. Local and Global tests passed.", ""

