#!/usr/bin/env bash
# netgame_fw を、ブラウザ(JS)のゲーム(Cloudflare Workers)に取り込む(コピー)。
#   bash tools/copy_to_js_game.sh <ゲームのリポジトリ> [サーバー側の置き場所] [クライアント側の置き場所]
#     既定: サーバー = <ゲーム>/src/netgame/   クライアント = <ゲーム>/public/js/netgame/
#     サーバー側: core.js / worker.js / text.js(サーバーの核と Worker の入口)・testkit.js(テスト用)・LICENSE・NOTICE・SOURCE_COMMIT
#     クライアント側: client.js(JS クライアント)・LICENSE・NOTICE・SOURCE_COMMIT
# コピーしたものは直接直さない(直すなら netgame_fw で直して、もう一度実行する)。出典の記載は README の「出典の書き方」。
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
GAME="${1:?使い方: bash tools/copy_to_js_game.sh <ゲームのリポジトリ> [サーバー側] [クライアント側]}"
SERVER="$GAME/${2:-src/netgame}"
CLIENT="$GAME/${3:-public/js/netgame}"
[ -d "$GAME" ] || { echo "ゲームのリポジトリが見つかりません: $GAME" >&2; exit 1; }
COMMIT="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
mkdir -p "$SERVER" "$CLIENT"
for f in core.js worker.js text.js testkit.js; do cp "$SRC/server/$f" "$SERVER/"; done
cp "$SRC/client-js/netgame/client.js" "$CLIENT/"
for d in "$SERVER" "$CLIENT"; do
  cp "$SRC/LICENSE" "$SRC/NOTICE" "$d/"
  echo "$COMMIT" > "$d/SOURCE_COMMIT"
done
echo "OK: netgame_fw $(echo "$COMMIT" | cut -c1-7) を取り込みました(サーバー: $SERVER / クライアント: $CLIENT)"
