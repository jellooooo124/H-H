#!/usr/bin/env python3
"""Small, explicit inward-dependency gate for migrated core modules."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'backend'/'app'
PURE=['domain/patient_scope.py','application/access_control.py','application/case_queries.py',
      'application/engagement_use_cases.py','application/fhir_use_cases.py','application/handoffs.py',
      'application/monitoring.py','application/ports.py']
FORBIDDEN=('fastapi','starlette','flask','sqlalchemy','sqlite3','psycopg','httpx',
           'app.infrastructure','app.presentation')

def imports(path):
    tree=ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            for alias in node.names:yield alias.name
        elif isinstance(node,ast.ImportFrom):
            if node.module:
                if node.level>0:
                    # For pure application modules, .infrastructure and .presentation are forbidden.
                    yield ('.'*node.level)+node.module
                else:yield node.module

def main():
    violations=[]
    for rel in PURE:
        for imported in imports(ROOT/rel):
            if any(imported==name or imported.startswith(name+'.') for name in FORBIDDEN):
                violations.append(f'{rel}: forbidden dependency {imported}')
            if imported.startswith(('.infrastructure','..infrastructure','.presentation','..presentation')):
                violations.append(f'{rel}: forbidden outward dependency {imported}')
    # This does NOT claim untouched legacy modules are clean.
    if violations:
        print('\n'.join(violations));raise SystemExit(1)
    print(f'PASS: {len(PURE)} migrated application/domain files do not import HTTP or database adapters')
if __name__=='__main__':main()
