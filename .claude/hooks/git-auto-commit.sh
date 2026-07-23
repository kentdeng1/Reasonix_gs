#!/usr/bin/env bash
# =============================================================================
# Claude Code Stop Hook — Git Auto-Commit
# 每次 AI 响应完成后自动提交变更到本地 git 仓库。
# 所有日志输出到 stderr，stdout 保留给 hook JSON 协议。
# =============================================================================
set -euo pipefail

# 1. 读取 Stop hook 输入，检测 stop_hook_active 防止无限循环
STOP_HOOK_ACTIVE=false
if [ -p /dev/stdin ] || [ -t 0 ]; then
  STDIN_DATA=""
  if read -r -t 1 FIRST_LINE 2>/dev/null; then
    STDIN_DATA="$FIRST_LINE"
    while IFS= read -r -t 0.1 LINE 2>/dev/null; do
      STDIN_DATA="$STDIN_DATA$LINE"
    done
  fi
  if echo "$STDIN_DATA" | grep -qi '"stop_hook_active"\s*:\s*true'; then
    STOP_HOOK_ACTIVE=true
  fi
fi

if [ "$STOP_HOOK_ACTIVE" = true ]; then
  echo "[git-auto-commit] stop_hook_active=true，跳过以避免无限循环" >&2
  echo '{"continue":true}'
  exit 0
fi

# 2. 检查是否跳过
if [ "${SKIP_AUTO_COMMIT:-}" = "true" ]; then
  echo "[git-auto-commit] SKIP_AUTO_COMMIT=true，跳过自动提交" >&2
  echo '{"continue":true}'
  exit 0
fi

# 3. 确认在 git 仓库中
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "[git-auto-commit] 非 git 仓库，跳过" >&2
  echo '{"continue":true}'
  exit 0
fi

# 4. 检查 git 用户配置
GIT_USER_NAME=$(git config user.name 2>/dev/null || echo "")
GIT_USER_EMAIL=$(git config user.email 2>/dev/null || echo "")
if [ -z "$GIT_USER_NAME" ] || [ -z "$GIT_USER_EMAIL" ]; then
  echo "[git-auto-commit] git user.name 或 user.email 未配置，跳过" >&2
  echo '{"continue":true}'
  exit 0
fi

# 5. 检查工作区变更
CHANGES=$(git status --porcelain 2>/dev/null)
if [ -z "$CHANGES" ]; then
  echo '{"continue":true}'
  exit 0
fi

# 6. 敏感文件检测（警告但不阻止）
SENSITIVE_PATTERNS=("\.env$" "\.pem$" "id_rsa" "id_ed25519" "credentials\.json$" "secret" "\.key$" "\.pfx$" "\.p12$")
while IFS= read -r LINE; do
  FILE_PATH=$(echo "$LINE" | sed 's/^...//')
  for PATTERN in "${SENSITIVE_PATTERNS[@]}"; do
    if echo "$FILE_PATH" | grep -qiE "$PATTERN"; then
      echo "[git-auto-commit] ⚠ 警告: 检测到可能的敏感文件 — $FILE_PATH" >&2
      break
    fi
  done
done <<< "$CHANGES"

# 7. 暂存并提交
git add -A
if git diff --cached --quiet 2>/dev/null; then
  echo '{"continue":true}'
  exit 0
fi

# 8. 生成 commit message
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
FILES_CHANGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
INS=$(git diff --cached --numstat 2>/dev/null | awk '{sum+=$1} END {print sum+0}')
DEL=$(git diff --cached --numstat 2>/dev/null | awk '{sum+=$2} END {print sum+0}')
FILE_LIST=$(git diff --cached --name-only 2>/dev/null | head -5 | tr '\n' ' ')
FILE_COUNT=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d ' ')
if [ "$FILE_COUNT" -gt 5 ] 2>/dev/null; then
  FILE_SUMMARY="$FILE_LIST ... (+$((FILE_COUNT - 5)) more)"
else
  FILE_SUMMARY="$FILE_LIST"
fi

COMMIT_TITLE="auto: $FILE_SUMMARY($TIMESTAMP)"
COMMIT_BODY="Files changed: $FILES_CHANGED
Insertions: +$INS, Deletions: -$DEL
Branch: $BRANCH"

# 9. 执行提交
if git commit -m "$COMMIT_TITLE" -m "$COMMIT_BODY" > /dev/null 2>&1; then
  COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
  echo "[git-auto-commit] ✓ 提交成功: $COMMIT_HASH — $COMMIT_TITLE" >&2
else
  echo "[git-auto-commit] ✗ 提交失败" >&2
  echo '{"continue":true}'
  exit 2
fi

# 10. 可选自动推送
if [ "${AUTO_PUSH:-}" = "true" ]; then
  REMOTE=$(git remote 2>/dev/null | head -1 || echo "")
  if [ -n "$REMOTE" ]; then
    if git push "$REMOTE" "$BRANCH" 2>&1 >&2; then
      echo "[git-auto-commit] ✓ 推送成功: $REMOTE/$BRANCH" >&2
    else
      echo "[git-auto-commit] ✗ 推送失败，请手动 git push" >&2
    fi
  else
    echo "[git-auto-commit] 未配置远程仓库，跳过推送" >&2
  fi
fi

# 11. 返回成功
echo '{"continue":true}'
exit 0
