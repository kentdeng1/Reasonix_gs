# AI Agent 自动化 Git 工作流配置指南

> **用途**：将此文件提供给任何 AI Agent（Claude Code、Cursor、Copilot 等），Agent 按本指南逐步执行，即可完成完整的自动 Git 提交工作流配置。
>
> **适用场景**：新建项目、空白文件夹、已有代码但未配置 git 的项目。

---

## 一、检测当前环境

执行以下命令检测环境状态：

```bash
# 1. 检查 git 是否安装
git --version

# 2. 检查是否在 git 仓库中
git rev-parse --git-dir 2>/dev/null && echo "已是 git 仓库" || echo "非 git 仓库"

# 3. 检查 git 用户配置
echo "user.name: $(git config user.name 2>/dev/null || echo '未设置')"
echo "user.email: $(git config user.email 2>/dev/null || echo '未设置')"

# 4. 检查 SSH 密钥
ls -la ~/.ssh/id_* 2>/dev/null || echo "无 SSH 密钥"

# 5. 检查远程仓库
git remote -v 2>/dev/null || echo "无远程仓库"
```

---

## 二、初始化 Git 环境

### 2.1 如果还不是 git 仓库，初始化

```bash
cd /你的项目目录
git init
git branch -M main
```

### 2.2 如果 git 用户未配置，设置（必须）

```bash
# 使用你的实际信息替换
git config user.name "你的名字"
git config user.email "你的邮箱@qq.com"
```

> ⚠️ commit 必须有 `user.name` 和 `user.email`，否则会失败。

---

## 三、创建项目文件

在项目根目录创建以下文件：

### 3.1 `.gitignore` — 忽略无关文件

创建 `.gitignore`，内容如下：

```gitignore
# --- 系统文件 ---
.DS_Store
Thumbs.db
desktop.ini
$RECYCLE.BIN/

# --- 编辑器 & IDE ---
.vscode/
.idea/
*.swp
*.swo
*~

# --- 环境变量 & 密钥（⚠ 永远不要提交） ---
.env
.env.*
!.env.example
*.pem
*.key
*.pfx
*.p12
credentials.json
secrets.yaml

# --- 依赖目录 ---
node_modules/
vendor/
__pycache__/
*.pyc
*.pyo
.venv/
venv/
env/

# --- 构建产物 ---
dist/
build/
out/
target/
*.class
*.jar
*.war
*.exe
*.dll
*.so
*.dylib
*.o
*.obj

# --- 日志 & 缓存 ---
*.log
logs/
.cache/
.tmp/
tmp/
temp/

# --- 测试覆盖 ---
coverage/
.nyc_output/
.coverage

# --- 数据库 ---
*.db
*.sqlite
*.sqlite3

# --- 压缩包 ---
*.zip
*.tar.gz
*.rar
*.7z

# --- Claude Code 个人配置（不提交） ---
.claude/settings.local.json
```

### 3.2 `.claude/settings.json` — Claude Code Stop Hook 配置

先创建目录，再创建文件：

```bash
mkdir -p .claude/hooks
```

创建 `.claude/settings.json`，内容如下：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"${CLAUDE_PROJECT_DIR}/.claude/hooks/git-auto-commit.sh\"",
            "timeout": 30,
            "statusMessage": "Auto-committing changes..."
          }
        ]
      }
    ]
  }
}
```

> **说明**：Stop hook 在 AI 每次响应完成后自动触发，执行 `git-auto-commit.sh`。

### 3.3 `.claude/hooks/git-auto-commit.sh` — 自动提交脚本

创建 `.claude/hooks/git-auto-commit.sh`，内容如下：

```bash
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
```

然后设置可执行权限：

```bash
chmod +x .claude/hooks/git-auto-commit.sh
```

---

## 四、配置 GitHub 远程仓库

### 4.1 如果还没有 SSH 密钥，生成

```bash
# 替换为你的邮箱
ssh-keygen -t ed25519 -C "你的邮箱@qq.com" -f ~/.ssh/id_ed25519 -N ""
```

### 4.2 添加 GitHub 主机密钥

```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

### 4.3 将公钥添加到 GitHub

**Agent 操作**：输出公钥内容，让用户手动添加到 GitHub。

```bash
cat ~/.ssh/id_ed25519.pub
```

**用户操作**：
1. 打开 https://github.com/settings/ssh/new
2. Title 填项目名或机器名
3. Key 粘贴公钥内容
4. 点击 Add SSH key

### 4.4 关联远程仓库

```bash
# 替换为你的 GitHub 仓库 SSH URL
git remote add origin git@github.com:你的用户名/仓库名.git

# 或者如果之前用 HTTPS 添加过，改为 SSH
git remote set-url origin git@github.com:你的用户名/仓库名.git
```

> ⚠️ 务必使用 SSH URL（`git@github.com:...`），HTTPS 在部分网络环境可能被阻断。

### 4.5 测试 SSH 连接

```bash
ssh -T git@github.com
# 预期输出: Hi xxx! You've successfully authenticated...
```

---

## 五、首次提交 & 推送

```bash
# 暂存所有文件
git add -A

# 首次提交
git commit -m "init: 项目初始化 + AI 自动提交工作流配置

- .gitignore: 忽略无关文件
- .claude/settings.json: Stop hook 配置
- .claude/hooks/git-auto-commit.sh: 自动提交脚本"

# 推送到 GitHub
git push -u origin main
```

---

## 六、验证工作流

### 6.1 手动测试脚本

```bash
# 无变更时应静默跳过
bash .claude/hooks/git-auto-commit.sh

# 创建测试变更
echo "test" > test.txt

# 应自动提交
bash .claude/hooks/git-auto-commit.sh

# 查看提交记录
git log --oneline -3

# 清理测试
rm test.txt
```

### 6.2 验证 hooks 配置

```bash
cat .claude/settings.json
# 应显示 Stop hook 配置
```

---

## 七、最终项目结构

配置完成后，项目目录结构应为：

```
你的项目/
├── .claude/
│   ├── settings.json              # Stop hook 配置
│   └── hooks/
│       └── git-auto-commit.sh     # 自动提交脚本（可执行）
├── .gitignore                     # 忽略规则
├── .git/                          # Git 仓库
├── AI_AGENT_SETUP_GIT.md          # 本指南（建议保留）
└── ... (你的代码文件)
```

---

## 八、Agent 执行清单

Agent 执行本指南时，按以下清单逐项确认：

- [ ] `git --version` 可用
- [ ] 已 `git init` 且分支为 `main`
- [ ] `user.name` 和 `user.email` 已配置
- [ ] `.gitignore` 已创建
- [ ] `.claude/settings.json` 已创建，配置了 Stop hook
- [ ] `.claude/hooks/git-auto-commit.sh` 已创建且可执行
- [ ] SSH 密钥已生成（`~/.ssh/id_ed25519`）
- [ ] 用户已将公钥添加到 GitHub
- [ ] `git remote add origin` 已配置（SSH URL）
- [ ] `ssh -T git@github.com` 认证成功
- [ ] 首次 commit 完成
- [ ] `git push -u origin main` 成功
- [ ] 手动运行 `git-auto-commit.sh` 验证通过

---

## 九、环境变量速查

| 变量 | 值 | 效果 |
|------|-----|------|
| `SKIP_AUTO_COMMIT` | `true` | 本次跳过自动提交 |
| `AUTO_PUSH` | `true` | 提交后自动推送到远程 |

---

## 十、常见问题

### Q: HTTPS 推送 SSL 错误 / 超时？

改用 SSH（本指南默认使用 SSH）：

```bash
git remote set-url origin git@github.com:用户名/仓库.git
```

### Q: 推送到已存在的仓库被拒绝？

```bash
git pull origin main --rebase
git push -u origin main
```

### Q: 新项目用 master 还是 main？

GitHub 默认用 `main`，本指南统一用 `main`：

```bash
git branch -M main
```
