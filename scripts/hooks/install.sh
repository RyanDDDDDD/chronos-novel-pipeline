#!/bin/sh
# 启用版本管理的 git hooks（一次性，clone 后运行）：
#   sh scripts/hooks/install.sh
# 之后 git 提交会使用 scripts/hooks/ 下的 hook，而非 .git/hooks/。

git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/pre-commit scripts/hooks/pre-merge-commit scripts/hooks/pre-push scripts/hooks/post-checkout 2>/dev/null || true
echo "✅ git hooks 已指向 scripts/hooks（core.hooksPath）。"
