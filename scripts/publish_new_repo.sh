#!/usr/bin/env bash
set -euo pipefail
NAME="${1:-hospital-at-home-care-coordination}"
if ! command -v gh >/dev/null; then echo 'Please install GitHub CLI: https://cli.github.com/' >&2; exit 2; fi
if ! command -v git >/dev/null; then echo 'git is required' >&2; exit 2; fi
gh auth status >/dev/null
if [[ ! -d .git ]]; then git init -b main; fi
if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  git add .
  git -c user.name='H@H Project Maintainer' -c user.email='local@example.invalid' commit -m 'feat: synthetic Hospital-at-Home clean-architecture research platform'
fi
# Refuse to overwrite a remote or create a public repo inadvertently.
if git remote get-url origin >/dev/null 2>&1; then echo 'An origin remote already exists; aborting' >&2; exit 2; fi
gh repo create "$NAME" --private --source=. --remote=origin --push
