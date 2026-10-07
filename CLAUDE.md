# netgame_fw

対戦ゲーム用ネットワーク・フレームワーク(サーバー: Cloudflare Workers + Durable Object / クライアント: Python・pygbag)。
全体像は `README.md`、設計は `docs/design.md`、通信は `docs/protocol.md`、ゲーム側の書き方は `docs/adapter.md` を読むこと。

## 基本ルール
- 返答・コメント・UI文字列・文書は日本語。
- クライアントの核(`client/netgame/` の pygame 非依存の部分)は、pygame を import しない。画面部品(`ui/`)だけが pygame を使う。
- ブラウザ(pygbag)で動くことが前提: Python の日本語をそのまま JS に渡さない(ASCII の JSON で受け渡す)/ JS 側の名前の先頭を `__` にしない / `websockets` などは文字列の `import_module` で読む / スレッドは PC 版だけ。
- サーバーの核(`server/*_core.js`)は Cloudflare に依存させない(`node --test` でテストできるように)。
- 変更したら、テスト(Python: `python -m pytest` / サーバー: `npm test`)を通す。サーバーを変えたら、`examples/pokoten/e2e.mjs`(wrangler dev に接続)でも確かめる。
- 作業は、ブランチを切って PR にする(`main` に直接 push しない)。
- ポコテン(mesaka/pokoten)の既存の動作を変えないことを、移行の間は最優先にする(`docs/migration.md`)。
