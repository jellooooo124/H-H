# Publish to a NEW private GitHub repository

Local Git repository creation and commit are automated with `scripts/publish_new_repo.sh`, but **creating a remote repository requires GitHub authority and an authenticated CLI**. The ChatGPT GitHub connector available during this build could read and update existing repositories but had no `create repository` action; no remote repository was created or pushed from this environment.

Run on your own machine after extracting the package (requires `git` and `gh` authenticated to the correct account):

```bash
cd hah_care_coordination_complete
bash scripts/publish_new_repo.sh hospital-at-home-care-coordination
```

This script creates a **private** new repository, configures the remote and pushes `main`. Run `gh auth status` beforehand; review organization/username and repository visibility. Never change the repository to public if it could contain student/course documents, identifiers, credentials or patient information. The .gitignore excludes `.env`, caches and data files. This repository contains synthetic examples and code only.

If you prefer to create the private repo manually in GitHub UI, use `git remote add origin <your private repo URL>` and `git push -u origin main` after `git init && git add . && git commit`.
