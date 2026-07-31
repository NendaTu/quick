"""
1. Summary: Repository map JSON generator.
2. Description: Walks the working tree, ignores excluded directories/files (such as dependencies, VCS metadata, database files, and markdown documentation), and extracts the one-line Part A summary from every hand-authored source file. Builds a flat JSON array indexing paths, raw GitHub URLs pointing to the development branch, and their descriptions, then serializes it to docs/map.json.
3. Context: Runs standalone or as part of verification workflows. Relies on Git commands to retrieve owner and repository telemetry.
"""
import os
import json
import re
import subprocess
import ast

def get_owner_repo():
    """
    Retrieves the owner and repository name from git remote configuration.
    """
    try:
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL).decode("utf-8").strip()
    except subprocess.CalledProcessError:
        try:
            remotes = subprocess.check_output(["git", "remote"], stderr=subprocess.DEVNULL).decode("utf-8").strip().split('\n')
            if remotes and remotes[0]:
                url = subprocess.check_output(["git", "remote", "get-url", remotes[0]], stderr=subprocess.DEVNULL).decode("utf-8").strip()
            else:
                url = ""
        except Exception:
            url = ""

    if not url:
        return "owner", "repo"

    if url.endswith(".git"):
        url = url[:-4]

    # SSH format: git@github.com:owner/repo
    # HTTPS format: https://github.com/owner/repo
    match = re.search(r'(?:git@github\.com:|https://github\.com/)([^/]+)/([^/]+)', url)
    if match:
        owner = match.group(1)
        repo = match.group(2)
        return owner, repo
    return "owner", "repo"

def is_excluded(path):
    """
    Returns True if the path matches any exclusion criteria.
    """
    parts = path.split(os.sep)

    # Exclude VCS metadata and dotfiles/dotdirectories
    if any(p.startswith('.') for p in parts):
        return True

    # Exclude dependency/vendor directories
    vendor_dirs = {'node_modules', '.venv', 'vendor', 'site-packages', 'target'}
    if any(p in vendor_dirs for p in parts):
        return True

    # Exclude database files and locks/WALs
    if any(path.endswith(ext) for ext in ['.db', '.db-wal', '.db-shm', '.pyc']):
        return True

    # Exclude logs/metrics/temp docs/archived docs/optimize docs
    if 'docs' in parts:
        if 'temp' in parts or 'archived' in parts or 'optimize' in parts:
            return True
        # Exclude docs/map.json itself
        if path == os.path.join('docs', 'map.json'):
            return True

    # Exclude documentation files (markdown, txt etc)
    if path.endswith('.md') or path.endswith('.txt'):
        if path not in ["AGENTS-old.md", "AGENTS-old_2.md", "AGENTS-old_3.md"]:
            return True

    # Exclude lock files and manifest lists
    lock_files = {
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'uv.lock',
        'Gemfile.lock', 'Cargo.lock', 'requirements.txt'
    }
    if os.path.basename(path) in lock_files:
        return True

    # Exclude .bak backup files
    if path.endswith('.bak'):
        return True

    # Exclude folders that contain __pycache__
    if '__pycache__' in parts:
        return True

    return False

def extract_summary(path):
    """
    Extracts the one-line summary from the Part A header comment of the file.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception:
        return ""

    # Check for executable launcher wrappers (backtest, compare, main)
    if os.path.basename(path) in ['backtest', 'compare', 'main']:
        for line in content.split('\n')[:30]:  # Only look at top 30 lines
            if line.strip().startswith('# 1. Summary:'):
                return line.split('# 1. Summary:', 1)[1].strip()
        # Fallback to search top lines
        top_lines = '\n'.join(content.split('\n')[:30])
        match = re.search(r'#\s*1\.\s*Summary:\s*(.*)', top_lines)
        if match:
            return match.group(1).strip()

    # Check Markdown files
    if path.endswith('.md'):
        for line in content.split('\n'):
            if line.strip().startswith('#'):
                return line.strip().lstrip('#').strip()
        for line in content.split('\n'):
            if line.strip():
                return line.strip()

    # Check Python files
    if path.endswith('.py'):
        try:
            tree = ast.parse(content, filename=path)
            docstring = ast.get_docstring(tree)
            if docstring:
                for line in docstring.split('\n'):
                    if line.strip().startswith('1. Summary:'):
                        return line.split('1. Summary:', 1)[1].strip()
        except Exception:
            pass

        # Fallback parser if AST parsing failed, but strictly limit to top 30 lines
        top_lines = '\n'.join(content.split('\n')[:30])
        match = re.search(r'1\.\s*Summary:\s*(.*)', top_lines)
        if match:
            return match.group(1).strip()

    # For JSON files (not currently present but for future proofing)
    if path.endswith('.json'):
        try:
            data = json.loads(content)
            desc = data.get("_description", "")
            if desc and "1. Summary:" in desc:
                return desc.split("1. Summary:", 1)[1].split("\n", 1)[0].strip()
            return desc
        except Exception:
            pass

    return ""

def generate_map():
    owner, repo = get_owner_repo()
    # Branch is fixed to development as per user requirements
    branch = "development"

    files_map = []

    # Walk directory tree
    for root, dirs, files in os.walk('.'):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, '.')

            if is_excluded(rel_path):
                continue

            summary = extract_summary(rel_path)
            # URL conforms exactly to GitHub raw content format on development branch
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/refs/heads/{branch}/{rel_path}"

            files_map.append({
                "path": rel_path,
                "raw_url": raw_url,
                "description": summary
            })

    # Sort map list by path for deterministic, beautifully ordered output
    files_map.sort(key=lambda x: x["path"])

    # Ensure docs directory exists
    os.makedirs("docs", exist_ok=True)

    with open("docs/map.json", "w", encoding="utf-8") as f:
        json.dump(files_map, f, indent=2)

    print(f"Successfully generated docs/map.json containing {len(files_map)} entries.")

if __name__ == "__main__":
    generate_map()
