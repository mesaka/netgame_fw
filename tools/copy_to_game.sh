#!/usr/bin/env bash
# netgame_fw の最新を、ゲームのリポジトリにコピーする(pygbag はアプリのフォルダ内のファイルしか梱包しないので、コピーで取り込む)。
#   bash tools/copy_to_game.sh <ゲームのリポジトリ>
#     <ゲーム>/netgame/         ← client/netgame/(クライアント。画面部品 `ui/` と `flow.py` は pygame を使う)+ LICENSE / NOTICE / SOURCE_COMMIT
#     <ゲーム>/server/netgame/  ← server/ の core.js / worker.js / text.js(サーバーの核と Worker の入口)と testkit.js(テスト用)
# コピーしたものは直接直さない(直すなら netgame_fw で直して、もう一度実行する)。ゲームの NOTICE への出典の記載は README の「出典の書き方」。
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="${1:?使い方: bash tools/copy_to_game.sh <ゲームのリポジトリ>}"
[ -d "$DST" ] || { echo "ゲームのリポジトリが見つかりません: $DST" >&2; exit 1; }
rm -rf "$DST/netgame" "$DST/server/netgame"
mkdir -p "$DST/netgame" "$DST/server/netgame"
cp -r "$SRC/client/netgame/." "$DST/netgame/"
find "$DST/netgame" -name __pycache__ -type d -prune -exec rm -rf {} +
for f in core.js worker.js text.js testkit.js; do cp "$SRC/server/$f" "$DST/server/netgame/"; done
cp "$SRC/LICENSE" "$SRC/NOTICE" "$DST/netgame/"
git -C "$SRC" rev-parse HEAD > "$DST/netgame/SOURCE_COMMIT" 2>/dev/null || echo "unknown" > "$DST/netgame/SOURCE_COMMIT"
echo "OK: netgame_fw $(cat "$DST/netgame/SOURCE_COMMIT" | cut -c1-7) を $DST に取り込みました"
