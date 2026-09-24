#!/usr/bin/env bash
# 版本号 → tag 名的唯一实现（AGENTS.md「版本号更新」）。
#
# 规则（2026-09-24 定案）：
#   - 0.x 阶段每个版本都是 beta → tag 为 vX.Y.Z-beta（同版本只发一次，故不编号）；
#   - v1.0.0 起：正式版 vX.Y.Z；预发布 vX.Y.Z-beta.N，且 __version__ 同时写
#     PEP 440 预发布形式（如 1.3.0b1），使 tag 与运行时版本一一对应。
#
# bump-version.sh 与 release-check.sh 都 source 本文件，避免同一规则两处各写一遍。

# 输出给定版本号对应的默认 tag 名（0.x 带 -beta；v1+ 为正式版名）
version_to_tag() {
    case "$1" in
    0.*) printf 'v%s-beta\n' "$1" ;;
    *) printf 'v%s\n' "$1" ;;
    esac
}

# 该版本是否已发过 tag：查 vX.Y.Z 与 vX.Y.Z-beta*
# （后者同时覆盖 0.x 的 -beta 与 v1+ 的 -beta.N）
# 命中则打印命中的 tag 名并返回 0；未命中返回 1
version_existing_tag() {
    local tag
    tag="$(git tag -l "v$1" "v$1-beta*" | head -1)"
    [ -n "$tag" ] || return 1
    printf '%s\n' "$tag"
}
