#!/usr/bin/env bash
# 安装 git hooks：把仓库自带的 .githooks/ 设为 git 的 hooks 目录。
#
# hooks 已提交进仓库（.githooks/），换机 / 重新 clone 后只需运行本脚本一次。
# 用法：bash scripts/install-git-hooks.sh

set -euo pipefail

# 定位仓库根目录（本脚本位于 <repo>/scripts/ 下）
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

git config core.hooksPath .githooks

echo "已安装 git hooks：$(git config core.hooksPath)"
echo "目录：$REPO_ROOT/.githooks/（commit-msg 校验提交信息格式）"
