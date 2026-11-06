# netgame_fw — 2人(将来はN人)対戦ゲーム用ネットワーク・フレームワーク

Pygame / pygbag(ブラウザ)の対戦ゲーム向けに、「接続 → 名前 → 相手の決め方(ランダム / ルーム+パスワード)→ 待機 → 準備OK →
対戦 → 決着 → 再戦 / 退出」の**流れ全体**を、ゲームに依存しない土台として提供する。
サーバーは Cloudflare Workers + Durable Object(WebSocket)。

元になったのは、[mesaka/pokoten](https://github.com/mesaka/pokoten) の「ネット対戦」(本番で動作確認済み)。
ポコテンは、このフレームワークの最初の利用者(アダプター)になる。

## 特長
- **対戦の「流れ全体」が入っている**: 名前入力 → 相手の決め方(ランダム / ルーム+4桁の数字) → 待機 → 準備OK → カウントダウン → 対戦 → 結果 → 再戦 / 退出、対戦前後のチャット。ゲームごとに書くのは「ゲームのルール(アダプター)」だけ。
- **ブラウザで動く**: クライアントは Python(pygame-ce)で、pygbag でブラウザ向けに出せる。PC 版(スレッド)とブラウザ版の両方を想定。
- **サーバーは Cloudflare だけ**: Workers + Durable Object(WebSocket)。別サーバーや DB は要らない。
- **2つの同期方式**: リアルタイム制、ターン制(ロックステップ。ずれはハッシュで検出)。
- **基本の画面部品つき**: `NetGameScene` / `Theme` / `Strings` / `Layout`。色・文言・配置は差し替えられる。

### 向いているもの / 向いていないもの
| | |
|---|---|
| 向いている | Pygame / pygbag で作った、2人対戦の小さなブラウザゲーム。ランダムマッチと、友だち同士のルーム対戦を足したい |
| 向いていない | 汎用の WebSocket ライブラリ(→ [PartyServer / PartySocket](https://github.com/cloudflare/partykit) など)。大人数・大規模なゲーム。強い不正対策が必要なゲーム(下の「注意」) |

### 注意(セキュリティ・不正対策)
- ターン制の v1(ロックステップ)は、**ルールがクライアントだけ**にあるため、手札など「相手に見せない情報」は守れない。隠し情報が必要なゲームには、いまは向かない(サーバー権威型は将来)。
- ルームの「パスワード」は**4桁の数字**で、友だち同士で遊ぶための簡単な合言葉。強い認証ではない。
- リアルタイム制は、各自が自分の盤面を計算して申告する方式。**クライアントの申告を、サーバーは完全には検証できない**(アダプターで検証する範囲まで)。

状態: **M0〜M6 まで実装済み**(サーバー・クライアントの核・画面部品・ポコテンへの取り込み・ターン制の見本・文書)。ポコテンは取り込み済みで、本番(Cloudflare)のブラウザで動作確認済み(2026-10-07)。ターン制の ○× は、ブラウザでは未確認。新しいゲームに組み込むなら、[docs/getting-started.md](docs/getting-started.md)。

```
npm test                         # サーバーのテスト(Node 22 以上)
pip install -r requirements-dev.txt && python -m pytest   # クライアント・画面部品のテスト(+ Node があれば、JS クライアントとの適合テスト)
npx wrangler dev -c examples/tictactoe/wrangler.jsonc --port 8787   # ローカルで動かす(○×。ポコテンは examples/pokoten/)
python examples/tictactoe/e2e.py # 本物の Workers ランタイムに2人分つないで、通しで確認(ターン制・画面部品つき)
node examples/cards/e2e-client.mjs  # JS クライアント(client-js)で、同じく本物の Workers に、実際の通信でつないで確認(自動再接続・保存した token での復帰)
node examples/cards/e2e.mjs      # サーバー権威型(v2)の見本を、同じく本物の Workers で確認(再接続・猶予切れのアラームも。先に examples/cards/wrangler.jsonc で wrangler dev)
node examples/pokoten/e2e.mjs    # 同じ確認(リアルタイム制・JS のクライアント)。Python のクライアントは examples/pokoten/e2e_client.py
```

## 2つの対戦方式(どちらもライブラリ化する)
| 方式 | 想定するゲーム | 同期の仕組み |
|---|---|---|
| **リアルタイム(realtime)** | ポコテンのような、各自が自分の盤面を同時に進める | 各自が自分で計算し、必要なイベント(おじゃま・盤面・負けの申告)だけを中継する |
| **ターン制(turns)** | ○×(見本)・次に作るターン制ゲーム | 手番はサーバーが管理。手(action)を全員に同じ順で配り、各自が同じルールで再現する(ロックステップ)。ずれはハッシュで検出する |

どちらも、接続〜準備OK〜チャット〜結果〜再戦/退出の流れ・画面部品は共通。

## 決まっていること
- 人数: いまは**2人対戦**。設計は最初から**N人(3人以上)に対応**できる形にするが、3人以上の開始方法・途中退出の扱いは**保留**(将来の拡張)。
- 範囲: サーバー、クライアントの通信・状態管理、**基本の画面部品**(名前入力・相手の決め方・ルーム/テンキー・待機・準備OK・カウントダウン・チャット窓・結果・退出)。
- ターン制は、**v1 = ロックステップ型**(ルールはクライアントだけ。手札など「相手に見せない情報」は守れない)。隠し情報が必要になったら、サーバー権威型(v2)を足す。
- ゲームへは、**コピー**で取り込む(`tools/copy_to_game.sh`。pygbag がアプリのフォルダ内のファイルだけを梱包するため)。
- 次のゲーム: アイデア段階(保留)。見本のターン制ゲーム(○×)で、流れは確かめた。

## 動作要件
| 用途 | 必要なもの |
|---|---|
| サーバーのテスト・ローカル実行 | Node.js 22 以上、`npx wrangler`(Cloudflare Workers) |
| クライアントのテスト | Python 3、`pip install -r requirements-dev.txt`(pytest, websockets) |
| ゲーム(クライアント) | Python + pygame-ce、ブラウザ版は [pygbag](https://github.com/pygame-web/pygbag) |
| 本番 | Cloudflare アカウント(Workers + Durable Object。SQLite バックエンドの Durable Object) |

## 使い始める
1. 見本を動かす: 上の `npx wrangler dev -c examples/tictactoe/wrangler.jsonc --port 8787`(○×)。
2. 自分のゲームに組み込む: [docs/getting-started.md](docs/getting-started.md)。`bash tools/copy_to_game.sh <ゲームのリポジトリ>` で `netgame/`(クライアント)と `server/netgame/`(サーバー)を**コピー**する(pygbag がアプリのフォルダ内のファイルしか梱包しないため)。コピーしたものは直接直さず、こちらで直して、もう一度コピーする。
3. ゲームのルールを「アダプター」に書く: [docs/adapter.md](docs/adapter.md)(ひな形は `templates/`)。

## ディレクトリ構成
```
server/      サーバーの核(core.js)・Worker の入口(worker.js)・文言(text.js)・テスト用(testkit.js)。Cloudflare に依存するのは worker.js だけ
client/      Python のクライアント(netgame/)。pygame に依存するのは ui/ と flow.py(NetGameScene)だけ
client-js/   JS のクライアント(netgame/client.js。画面を含まない・依存なし)と、そのテスト
templates/   新しいゲーム用のひな形(server/・client/)
examples/    見本: tictactoe(ターン制)、pokoten(リアルタイム制)、guess3(N人の例)
docs/        設計・プロトコル・アダプター・画面部品・移行の文書
tools/       コピー(copy_to_game.sh)・フォント生成・比較ツール
tests/       クライアント(pytest)のテスト。tests/conformance/ は、JS と Python のクライアントの適合テスト(同じシナリオ・同じ golden)
```

## 文書
- [docs/design.md](docs/design.md) — 全体設計(構成・N人モデル・サーバー構成・画面部品・pygbag の制約・リスク)
- [docs/protocol.md](docs/protocol.md) — 通信プロトコル v1(メッセージ、状態、エラー)
- [docs/getting-started.md](docs/getting-started.md) — **新しいゲームに組み込む手順**(取り込み・サーバー・クライアント・フォント・pygbag・確認)
- [docs/adapter.md](docs/adapter.md) — ゲームが書くもの(アダプター)の仕様。リアルタイム用・ターン制用
- [docs/ui.md](docs/ui.md) — 画面部品(`NetGameScene`・`Theme`・`Strings`・`Layout`)の使い方
- [docs/migration.md](docs/migration.md) — ポコテンから移す手順(M0〜M6)と、現在の通信との対応表
- [docs/client-js.md](docs/client-js.md) — **JS クライアント**(ブラウザ用。使いかた・再接続・適合テスト)。Python の v=2 の使いかたも
- [docs/design-v2.md](docs/design-v2.md) — **v2 の設計と計画(M12 まで実装済み)**: サーバー権威型・再接続・JS クライアント(正式)・部屋コード設定。ブラウザ(JS)のゲームにも使える汎用ライブラリにするための計画(M7〜M12)

## ロードマップ
M0 設計・仕様 → M1 サーバー → M2 クライアントの核 → M3 画面部品 → M4 ポコテンを置き換え → M5 ターン制(○×)と見本 → M6 文書(いまここまで完了)。
詳細は [docs/migration.md](docs/migration.md)。
次は **M7〜M12(汎用化)**: サーバー権威型(隠し情報)・再接続・JS クライアントを足し、hiro-hoshi-kazu.com の花札2作品を `netgame_fw` の上で動かす。計画は [docs/design-v2.md](docs/design-v2.md)。**M7(仕様)・M8(サーバー権威型 `authoritative`・部屋と進行の設定・入室失敗の制限)・M9(再接続: token・切断の猶予・`resume`・`presence`・休止からの復帰)・M10(JS クライアント `client-js/` と、Python との適合テスト)・M11〜M12(hiro-hoshi-kazu.com の花札2作品=こいこい・花合わせが、この上で動く。旧版の PartyServer は撤去)は実装済み**。実際の使いかたの例は、[mesaka/hiro-hoshi-kazu-web](https://github.com/mesaka/hiro-hoshi-kazu-web) の `src/awase-netgame.js` / `src/koikoi-netgame.js`(アダプター各約40行)と `public/js/net-ng.js`(ブラウザ側)。

## ライセンス
[Apache License 2.0](LICENSE)。**出典の記載が条件**になる(下の「出典の書き方」)。

### 出典の書き方(このフレームワークを使うゲーム・派生物へ)
Apache License 2.0 の第4条(d)により、`netgame_fw` を取り込んだ(改変した場合を含む)ゲームは、[NOTICE](NOTICE) の帰属表示を、**次のいずれかに入れる**:
- ゲームのリポジトリの `NOTICE` ファイル(配布物に含める)
- ソース・ドキュメント(README など)
- ゲームの画面(クレジット表示など)

書き方の例(そのまま使える):
```
netgame_fw (c) 2026 mesaka  https://github.com/mesaka/netgame_fw  (Apache License 2.0)
```
あわせて、`LICENSE` のコピーを、取り込んだコードの近く(`netgame/` フォルダなど)に残すこと。改変したファイルには、改変したことが分かる表示を付けること(第4条(b))。

## 状況とサポートの方針
- **個人のプロジェクト**で、バージョンは 0.x。互換性のない変更を予告なく行うことがある(取り込んだ版は、ゲーム側の `netgame/SOURCE_COMMIT` で分かる)。
- 無保証(Apache License 2.0 第7条・第8条)。動作や対応の約束はしない。
- **Issue** は歓迎(不具合・質問・要望)。ただし、返信や対応の時期は約束できない。
- **Pull Request** は、先に Issue で相談してほしい(方針に合わないものは、取り込めないことがある)。変更するときは、テスト(`npm test` と `python -m pytest`)を通すこと。
- **脆弱性**は、公開の Issue に詳細を書かず、GitHub の Security タブの「Report a vulnerability」から非公開で報告してほしい。

## 利用例
- [mesaka/pokoten](https://github.com/mesaka/pokoten) — ポコテン。リアルタイム制の最初の利用者。
- `examples/tictactoe/` — ターン制(○×)の見本。

## 関連
- 汎用の WebSocket ライブラリには、[PartyServer / PartySocket](https://github.com/cloudflare/partykit) がある。netgame_fw は、「対戦ゲームの流れと画面」までを含む、Pygame / pygbag 向けの専用の土台で、これらには依存していない。

## 未定(保留)
- 横長の専用レイアウト(いまは基準 480×800 を中央に置く)
- 3人以上の開始方法(ルームは「作った人が開始」/ランダムは「人数がそろうまで」など)、途中で抜けた人の扱い
- 次のゲームの名前・ルール
