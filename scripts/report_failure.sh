#!/usr/bin/env bash
# MONITOR agent: opens (or updates) a GitHub Issue when any agent run fails,
# so you get an email/phone notification from GitHub. Needs GH_TOKEN.
set -uo pipefail
WHAT="${1:-agent}"
URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
gh label create agent-failure --color d73a4a --description "Automated agent failure" 2>/dev/null || true
EXISTING=$(gh issue list --label agent-failure --state open --search "$WHAT failed" --json number -q '.[0].number')
BODY="Run failed: $URL
Time (UTC): $(date -u '+%Y-%m-%d %H:%M')
Last log lines:
\`\`\`
$(tail -n 30 state/runs.jsonl 2>/dev/null | grep -i error | tail -n 3 | cut -c1-1500)
\`\`\`"
if [ -n "$EXISTING" ]; then
  gh issue comment "$EXISTING" --body "$BODY"
else
  gh issue create --title "🚨 $WHAT failed" --label agent-failure --body "$BODY"
fi
