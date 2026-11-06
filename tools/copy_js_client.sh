#!/usr/bin/env bash
# netgame_fw の JS クライアント(client-js/netgame/)を、ブラウザ(JS)のゲームにコピーする。
#   bash tools/copy_js_client.sh <コピー先のフォルダ>      例: bash tools/copy_js_client.sh ../mygame/public/js/netgame
#     <コピー先>/client.js, LICENSE, NOTICE, SOURCE_COMMIT
# コピーしたものは直接直さない(直すなら netgame_fw で直して、もう一度実行する)。出典の記載は README の「出典の書き方」。
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="${1:?使い方: bash tools/copy_js_client.sh <コピー先のフォルダ>}"
mkdir -p "$DST"
cp "$SRC/client-js/netgame/client.js" "$DST/"
cp "$SRC/LICENSE" "$SRC/NOTICE" "$DST/"
git -C "$SRC" rev-parse HEAD > "$DST/SOURCE_COMMIT" 2>/dev/null || echo "unknown" > "$DST/SOURCE_COMMIT"
echo "OK: netgame_fw JS クライアント $(cut -c1-7 "$DST/SOURCE_COMMIT") を $DST に取り込みました"
