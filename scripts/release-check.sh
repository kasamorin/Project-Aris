#!/usr/bin/env bash
# 版本发布前检查（AGENTS.md「Git 开发流程」「版本号更新」）：
#   1. 版本号结构：唯一源是 src/aris/__init__.py；pyproject.toml 走 dynamic version
#      （不得再出现静态 version），uv.lock 不记录本项目版本
#   2. 已安装元数据与源一致（uv cache-keys 是否生效的兜底）
#   3. uv.lock 与 pyproject.toml 同步（uv lock --check）
#   4. 当前分支是 develop 且无未合并的本地 feature 分支
#   5. 该版本的 tag 尚未被占用
# 通过则输出发布流程提示并 exit 0；否则列出问题 exit 1。
# 用法：bash scripts/release-check.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYPROJECT="pyproject.toml"
VERSION_FILE="src/aris/__init__.py"

fail=0

echo "===== 发布检查 ====="

# ---- 1. 版本号单一来源 ----
ver="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' "$VERSION_FILE" | head -1)"
if ! printf '%s' "$ver" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "[FAIL] $VERSION_FILE 的版本号缺失或不合法（PEP 440 的 X.Y.Z）: '${ver:-<缺失>}'"
    fail=1
else
    echo "[ ok ] 版本唯一源 $VERSION_FILE: v$ver"
fi

if grep -qE '^version *= *"' "$PYPROJECT"; then
    echo "[FAIL] $PYPROJECT 仍有静态 version —— 版本号只能有一处，见 AGENTS.md「版本号更新」"
    fail=1
elif ! grep -qE '^dynamic *= *\["version"\]' "$PYPROJECT"; then
    echo "[FAIL] $PYPROJECT 未声明 dynamic = [\"version\"]"
    fail=1
else
    echo "[ ok ] $PYPROJECT 使用 dynamic version（无第二处手写）"
fi

if ! grep -qF 'attr = "aris.__version__"' "$PYPROJECT"; then
    echo "[FAIL] $PYPROJECT 缺少 [tool.setuptools.dynamic] version = {attr = \"aris.__version__\"}"
    fail=1
fi
if ! grep -qE "^cache-keys *=.*$VERSION_FILE" "$PYPROJECT"; then
    echo "[FAIL] $PYPROJECT 缺少 [tool.uv] cache-keys 指向 $VERSION_FILE（改了版本 uv 不会重建元数据）"
    fail=1
fi

# ---- 2. 已安装元数据与源一致（venv 存在时才查）----
if [ -x ".venv/bin/python" ]; then
    installed="$(.venv/bin/python -c 'import importlib.metadata as m; print(m.version("aris"))' 2>/dev/null || echo '')"
    if [ "$installed" = "$ver" ]; then
        echo "[ ok ] 已安装元数据一致: aris==$installed"
    else
        echo "[FAIL] 已安装元数据 ($installed) 与 $VERSION_FILE ($ver) 不一致"
        echo "         跑一次 uv sync（或用 scripts/bump-version.sh 改版本）"
        fail=1
    fi
else
    echo "[skip] 未找到 .venv，跳过已安装元数据检查"
fi

# ---- 3. uv.lock 与 pyproject.toml 同步 ----
if lock_out="$(uv lock --check 2>&1)"; then
    echo "[ ok ] uv.lock 与 $PYPROJECT 同步"
else
    echo "[FAIL] uv.lock 不同步，跑一次 uv lock 后重试："
    printf '%s\n' "$lock_out" | sed 's/^/         /'
    fail=1
fi

# ---- 4. 分支状态 ----
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

# ---- 5. tag 未被占用 ----
if [ -n "$ver" ] && git rev-parse -q --verify "refs/tags/v$ver" >/dev/null; then
    echo "[FAIL] tag v$ver 已存在，不能重复发布"
    fail=1
else
    echo "[ ok ] tag v${ver:-?} 尚未占用"
fi

# ---- 6. 汇总 ----
echo
if [ "$fail" -eq 0 ]; then
    echo "结果：PASS（可进入版本发布流程）"
    echo "  1. 在 develop 上 bump 版本：bash scripts/bump-version.sh <版本|patch|minor|major>"
    echo "  2. 提交 chore(release) 并合并回 main（git merge --no-ff）"
    echo "  3. git tag v$ver 并 git push origin develop main && git push origin v$ver"
    echo "  4. 打 tag 后建议复查 git show v$ver --stat"
    exit 0
fi

echo "结果：FAIL（先解决以上问题再重试）"
exit 1
