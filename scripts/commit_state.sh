#!/usr/bin/env bash
# Commits the agent's memory (state/) back to the repo. Keeps the repo active so
# GitHub never auto-disables the scheduled workflows (it does after 60 idle days).
set -euo pipefail
MSG="${1:-agent run}"
git config user.name  "gta6-tamil-agent"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add state/
if git diff --cached --quiet; then echo "state unchanged"; exit 0; fi
git commit -q -m "agent: ${MSG} [skip ci]"
for i in 1 2 3 4; do
  # other agents may have pushed meanwhile; on conflicting JSON keep this run's version
  if git pull -q --rebase -X theirs && git push -q; then echo "state pushed"; exit 0; fi
  sleep $((i * 5))
done
echo "could not push state" >&2; exit 1
