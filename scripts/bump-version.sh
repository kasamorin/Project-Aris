#!/usr/bin/env bash
# 版本号 bump（AGENTS.md「版本号更新」）：
#   版本号唯一源是 src/aris/__init__.py 的 __version__，本脚本是唯一的改法。
#   pyproject.toml 用 dynamic version 从该文件读取，uv.lock 不记录本项目版本；
#   因此不会再有「三处要同步」的问题，也不需要额外的同步提交。
#
# 用法：
#   bash scripts/bump-version.sh 0.5.0     # 指定版本（PEP 440 的 X.Y.Z）
#   bash scripts/bump-version.sh patch     # 0.4.1 -> 0.4.2
#   bash scripts/bump-version.sh minor     # 0.4.1 -> 0.5.0
#   bash scripts/bump-version.sh major     # 0.4.1 -> 1.0.0
#
# 只改文件、不提交；跑完后按提示提交并走发布流程（release-check.sh → main → tag）。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# 版本号 → tag 名的规则与 release-check.sh 共用（见 lib-version.sh）
# shellcheck source=lib-version.sh
. "$REPO_ROOT/scripts/lib-version.sh"

VERSION_FILE="src/aris/__init__.py"

# ---- 参数 ----
if [ $# -ne 1 ]; then
    echo "用法：bash scripts/bump-version.sh <版本 | patch | minor | major>" >&2
    exit 2
fi

current="$(sed -n 's/^__version__ *= *"\(.*\)"/\1/p' "$VERSION_FILE" | head -1)"
if [ -z "$current" ]; then
    echo "错误：$VERSION_FILE 里找不到 __version__" >&2
    exit 1
fi

case "$1" in
patch | minor | major)
    IFS=. read -r cur_major cur_minor cur_patch <<<"$current"
    case "$1" in
    patch) cur_patch=$((cur_patch + 1)) ;;
    minor)
        cur_minor=$((cur_minor + 1))
        cur_patch=0
        ;;
    major)
        cur_major=$((cur_major + 1))
        cur_minor=0
        cur_patch=0
        ;;
    esac
    new="$cur_major.$cur_minor.$cur_patch"
    ;;
*) new="$1" ;;
esac

# ---- 校验 ----
# 只放行 X.Y.Z：setuptools 按 PEP 440 解析，写错会直接构建失败
# （实测 `9.9.9-test` 报 InvalidVersion）。预发布版本请手改本文件并自行确认。
if ! printf '%s' "$new" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "错误：版本号必须是 X.Y.Z 形式，收到 '$new'" >&2
    exit 2
fi
if [ "$new" = "$current" ]; then
    echo "错误：新版本与当前版本相同（$current）" >&2
    exit 2
fi

# bump 必须在干净的 develop 上做，否则容易把无关改动混进发布提交
branch="$(git symbolic-ref --short HEAD 2>/dev/null || echo '<detached>')"
if [ "$branch" != "develop" ]; then
    echo "错误：当前分支是 $branch，版本 bump 必须在 develop 上进行" >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "错误：工作区不干净，先提交或 stash 再 bump" >&2
    git status --short >&2
    exit 1
fi
if existing="$(version_existing_tag "$new")"; then
    echo "错误：tag $existing 已存在，不能重复发布" >&2
    exit 1
fi

# ---- 改源 + 刷新锁文件与已安装元数据 ----
sed -i "s/^__version__ *= *\"$current\"/__version__ = \"$new\"/" "$VERSION_FILE"
echo "版本号 $current -> $new（$VERSION_FILE）"

uv lock
uv sync

tag="$(version_to_tag "$new")"
echo
echo "完成，当前版本：$(uv run aris --version)"
echo "下一步："
echo "  1. git add $VERSION_FILE uv.lock && git commit -m 'chore(release): 版本号 bump 至 v$new'"
echo "  2. bash scripts/release-check.sh"
echo "  3. git checkout main && git merge --no-ff develop -m 'chore(release): $tag —— <一句话总结>'"
echo "  4. git tag $tag && git push origin develop main && git push origin $tag"
case "$new" in
0.*) echo "     （0.x 阶段 tag 带 -beta 后缀）" ;;
*) echo "     （v1.0.0 起为正式版 tag；若要发 v$new 的预发布，用 v$new-beta.N）" ;;
esac
