#!/usr/bin/env bash
# 版本发布前检查（AGENTS.md「Git 开发流程」）：
#   1. 版本号三源一致：pyproject.toml / src/aris/__init__.py / uv.lock
#   2. 当前分支是 develop 且无未合并的本地 feature 分支
# 通过则输出发布流程提示并 exit 0；否则列出问题 exit 1。
# 用法：bash scripts/release-check.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

fail=0

echo "===== 发布检查 ====="

# ---- 1. 版本号三源一致 ----
py_ver="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
init_ver="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' src/aris/__init__.py | head -1)"
lock_ver="$(awk '/^name = "aris"$/ {f=1} f && /^version = / {print $3; exit}' uv.lock | tr -d '"')"

if [ -n "$py_ver" ] && [ "$py_ver" = "$init_ver" ] && [ "$py_ver" = "$lock_ver" ]; then
    echo "[ ok ] 版本三源一致: v$py_ver（pyproject.toml / __init__.py / uv.lock）"
else
    echo "[FAIL] 版本三源不一致："
    echo "         pyproject.toml      = ${py_ver:-<缺失>}"
    echo "         src/aris/__init__.py = ${init_ver:-<缺失>}"
    echo "         uv.lock             = ${lock_ver:-<缺失>}"
    fail=1
fi

# ---- 2. 分支状态 ----
cur="$(git symbolic-ref --short HEAD 2>/dev/null || echo '<detached>')"
if [ "$cur" = "develop" ]; then
    echo "[ ok ] 当前分支: develop"
else
    echo "[FAIL] 当前分支: $cur（发布检查应在 develop 上进行）"
    fail=1
fi

unmerged=""
for b in $(git for-each-ref --format='%(refname:short)' refs/heads/); do
    case "$b" in
    develop | main | oldWish) continue ;;
    esac
    if ! git merge-base --is-ancestor "$b" develop 2>/dev/null; then
        unmerged="$unmerged $b"
    fi
done
if [ -z "$unmerged" ]; then
    echo "[ ok ] 无未合并的本地 feature 分支"
else
    echo "[FAIL] 存在未合并的本地分支:$unmerged（先合并回 develop 再发布）"
    fail=1
fi

# ---- 3. 汇总 ----
echo
if [ "$fail" -eq 0 ]; then
    echo "结果：PASS（可进入版本发布流程）"
    echo "  1. 在 develop 上 bump 版本（pyproject.toml / __init__.py / uv.lock 三源同步）"
    echo "  2. git merge --no-ff 合并回 main，提交信息用对应前缀一句话总结"
    echo "  3. git tag vX.Y.Z 并 git push --tags"
    echo "  4. 打 tag 后建议复查 git show vX.Y.Z --stat"
    exit 0
fi

echo "结果：FAIL（先解决以上问题再发布）"
exit 1