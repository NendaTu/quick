"""
1. Summary: Internal utility script to pull and print existing docstrings from Python modules.
2. Description: Walks target files and parses AST representations to extract top-level docstrings.
3. Context: Used for code analysis and metadata audits.
"""
import os
import ast

from list_targets import targets

for t in sorted(targets):
    if t.endswith('.py'):
        try:
            with open(t, 'r') as f:
                content = f.read()
            tree = ast.parse(content, filename=t)
            docstring = ast.get_docstring(tree)
            if docstring:
                print(f"=== {t} ===")
                first_lines = docstring.strip().split('\n')[:4]
                print('\n'.join(first_lines))
                print()
        except Exception as e:
            pass
