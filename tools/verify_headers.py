"""
1. Summary: Validator verifying all target files contain correct 3-part headers.
2. Description: Parses the AST representation of Python files and checks launcher files to verify they contain Summary, Description, and Context tags matching our Part A standards.
3. Context: Runs as a final validation pass.
"""
import os
import ast
from list_targets import targets

def verify_headers():
    mismatches = 0
    for t in sorted(targets):
        if not os.path.exists(t):
            print(f"File not found: {t}")
            mismatches += 1
            continue

        with open(t, 'r', encoding='utf-8') as f:
            content = f.read()

        if t.endswith('.py'):
            try:
                tree = ast.parse(content, filename=t)
                doc = ast.get_docstring(tree)
                if not doc:
                    print(f"Mismatch: {t} is missing a module-level docstring.")
                    mismatches += 1
                    continue
                if "1. Summary:" not in doc or "2. Description:" not in doc or "3. Context:" not in doc:
                    print(f"Mismatch: {t} docstring does not match the 3-part format.")
                    mismatches += 1
            except Exception as e:
                print(f"Mismatch: {t} failed to parse AST: {e}")
                mismatches += 1

        elif t in ['backtest', 'compare', 'main']:
            if not content.startswith('#!'):
                print(f"Mismatch: {t} is missing a shebang.")
                mismatches += 1
                continue
            lines = content.split('\n')
            has_summary = any(l.strip().startswith('# 1. Summary:') for l in lines[:10])
            has_desc = any(l.strip().startswith('# 2. Description:') for l in lines[:10])
            has_context = any(l.strip().startswith('# 3. Context:') for l in lines[:10])

            if not (has_summary and has_desc and has_context):
                print(f"Mismatch: {t} launcher is missing some of the 3-part shebang comments.")
                mismatches += 1

    if mismatches == 0:
        print("Verification SUCCESS: All target files have matching 3-part headers!")
    else:
        print(f"Verification FAILURE: Found {mismatches} mismatches.")

if __name__ == "__main__":
    verify_headers()
