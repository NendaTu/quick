"""
1. Summary: Internal utility script to count and list all files in scope for metadata headers.
2. Description: Analyzes directory layouts and filters out VCS, build, and test artifacts.
3. Context: Used during build audits and repository mapping.
"""
import os

def is_excluded(path):
    parts = path.split(os.sep)
    # Exclude dotfiles/dotdirs
    if any(p.startswith('.') for p in parts):
        return True
    # Exclude temp docs / archived docs / optimize markdown
    if 'docs' in parts:
        if 'temp' in parts or 'archived' in parts or 'optimize' in parts:
            return True
        if path.endswith('.md'):
            return True
        if path.endswith('.json'):
            return True
    # Exclude __pycache__ and .pyc
    if '__pycache__' in parts or path.endswith('.pyc'):
        return True
    # Exclude db files and backup files
    if path.endswith('.db') or path.endswith('.db-wal') or path.endswith('.db-shm') or path.endswith('.bak'):
        return True
    # Exclude requirements.txt
    if path == 'requirements.txt':
        return True
    # Exclude markdown files
    if path.endswith('.md'):
        return True
    return False

targets = []
for root, dirs, files in os.walk('.'):
    for f in files:
        full_path = os.path.join(root, f)
        rel_path = os.path.relpath(full_path, '.')
        if not is_excluded(rel_path):
            targets.append(rel_path)

print(f"Total target files: {len(targets)}")
for t in sorted(targets):
    print(t)
