#!/usr/bin/env bash
# 每日更新黄金看板并推送到 GitHub
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

CRED="$HOME/.git-credentials"
[ -f "$CRED" ] || { echo "NO_CRED"; exit 1; }

python3 scripts/update_dashboard.py || exit 1

git add -A
if git diff --staged --quiet; then
  echo "NO_CHANGES"
  exit 0
fi
git -c user.name="gold-dashboard-bot" -c user.email="bot@users.noreply.github.com" \
    commit -q -m "chore: daily update $(TZ=Asia/Shanghai date +%F)"
for i in 1 2 3 4 5 6; do
  if git -c credential.helper="store --file=$CRED" push origin main 2>&1 | tail -2; then
    echo "PUSHED"
    exit 0
  fi
  sleep 10
done
echo "PUSH_FAILED"
exit 1
