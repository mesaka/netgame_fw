# 新しいゲームに組み込む手順

netgame_fw を使って、対戦ゲーム(Pygame / pygbag + Cloudflare)に、ネット対戦(接続 → 名前 → ランダム/ルーム → 準備OK → 対戦 → 結果 → 再戦/退出、チャット)を足す手順。実際の例は、[mesaka/pokoten](https://github.com/mesaka/pokoten)(リアルタイム制)と、`examples/tictactoe/`(ターン制)。

## 0. 前提
- ゲームは、Python(pygame-ce)で、pygbag でブラウザに出せること。サーバーは Cloudflare(Workers + Durable Object。Workers Builds で、ブランチごとにプレビュー、`main` で本番)。
- 対戦方式を決める: **リアルタイム**(各自が自分の盤面を同時に進める。必要なイベントだけ中継)か、**ターン制(ロックステップ)**(手番はサーバーが管理。手を全員に同じ順で配って、各自が同じルールで再現。ルールはクライアントだけ=隠し情報は守れない)。
- いまは2人対戦。3人以上の開始方法・途中退出の扱いは未定(サーバーの核は N 人対応。`examples/guess3/`)。

## 1. 取り込む(コピー)
pygbag はアプリのフォルダ内のファイルしか梱包しないので、サブモジュールではなく**コピー**する。
```
bash <netgame_fw>/tools/copy_to_game.sh <ゲームのリポジトリ>
```
- `netgame/`(クライアント)と `server/netgame/`(サーバーの核・入口)ができる。コピーしたものは**直接直さない**(直すなら netgame_fw で直して、もう一度コピー)。取り込んだ版は `netgame/SOURCE_COMMIT`。
- `netgame/LICENSE` `netgame/NOTICE` も入る。**出典の記載が条件**(Apache-2.0)。README の「出典の書き方」の一文を、ゲームの `NOTICE` か README か画面に入れる。
- ゲーム側のリポジトリに、同じコピーのための短いスクリプト(`tools/sync_netgame.sh`。ポコテンの例)を置いておくと、更新が楽。

## 2. サーバー(Cloudflare)
`templates/server/` を、ゲームにコピーして書き換える。
| ファイル | 置き場所 | 中身 |
|---|---|---|
| `adapter.js` | `server/adapter.js` | ゲームのルール(サーバー側): `id`・`mode`・人数・設定の正規化・組み合わせの条件・中継するイベントの検証(realtime)/手の形の検証(turns)・結果の決め方。仕様は `docs/adapter.md` 1 |
| `worker.js` | `server/worker.js` | `createGameWorker({ mygame })` を呼ぶだけの入口 |
| `wrangler.jsonc` | ゲームのルート | Durable Object(`HUB` / `Hub`)・`new_sqlite_classes` のマイグレーション・**`previews` の Durable Object**・`assets.run_worker_first: ["/ws"]` |

注意:
- `class_name`(`Hub`)は `worker.js` の `export { Hub }` と同じ名前にする。`previews.durable_objects` がないと、ブランチのプレビュー(`wrangler preview`)のビルドが失敗する。
- 既存の Durable Object のクラスを置き換えるときは、マイグレーションを足す(例: `{ "tag": "v2", "new_sqlite_classes": ["Hub"], "deleted_classes": ["Lobby"] }`)。
- 静的ファイルは `build/web`(pygbag の出力)。PC で試すときは、空の `build/web` を作って `npx wrangler dev`。
- 接続先は、同じサイトの `/ws`(ページの URL に `?server=wss://…` を付けると変えられる)。PC のクライアントは、環境変数 `NETGAME_SERVER`(既定 `ws://localhost:8787/ws`)と `pip install websockets`。
- ブラウザ以外の接続(Origin なし)は通る。別のサイトのページからの接続は、`createGameWorker` が断る。

## 3. クライアント
`templates/client/adapter.py` を、ゲームにコピーして書く(リアルタイム制)。ターン制は `TurnAdapter`(`examples/tictactoe/ttt_client.py`)。仕様は `docs/adapter.md` 2。

```python
from netgame.flow import NetGameScene
class Net(NetGameScene):                       # メニューの「ネット対戦」から、この場面に移る
    size = (480, 800)
    def __init__(self):
        super().__init__(MyGameAdapter(), theme=Theme(font=jp_font, background=draw_background),
                         strings={...})        # 文言の上書き(任意)
# 毎フレーム: r = scene.handle(ev) / r = scene.update()(r == "menu" ならメニューへ)/ scene.draw(screen)
```
- アダプターが受け持つのは、対戦中の「動かす・描く」だけ。名前・ルーム・待機・準備OK・カウントダウン・チャット・結果・退出・ブラウザの入力欄は `NetGameScene` が受け持つ(`docs/ui.md`)。
- 画面は、基準の 480×800(縦長)を、大きい画面の中央に置く。右の列(x=352〜)に、チャット・メニュー・結果のボタンが出るので、盤面はそこを避ける。
- 音・音量ボタン・名前の保存は、アダプターの `sound` / `bgm` / `handle_global` / `load_name` / `save_name` で、ゲームのものにつなぐ。

## 4. フォント
軽量フォント(使う文字だけ)を使うなら、netgame の画面の文字・名前やチャットに入力できる文字も入れる。
```
python <netgame_fw>/tools/build_font.py --font 元フォント.ttf --out assets/fonts/jp.ttf --strings strings.py:S
```
- 入る文字: ASCII・netgame の既定の文言(`netgame/strings_ja.py`)・名前/チャットに入力できる文字(かな・全角英数記号。漢字は容量のため入れない)・`--strings` の辞書の値・`--text` / `--text-file`。`fonttools` が必要。
- netgame を更新(コピー)したら、フォントも作り直す(新しい文言の文字が入る)。
- 元フォントのライセンスは、ゲーム側で守る(M PLUS Rounded 1c は SIL OFL)。

## 5. pygbag(ブラウザ)で守ること
- Python の日本語の文字列を、そのまま JS に渡さない(文字化けする)。netgame は、ASCII の JSON で受け渡している。ゲーム側で JS を触るときも同じ。
- JS 側の名前の先頭を `__` にしない(Python のクラスの中で、名前が書き換わる)。
- `websockets` などは、文字列の `import_module` で読む(pygbag の依存の解析に拾われないように)。スレッドは PC 版だけ。
- 文字の入力は、ブラウザでは画面に重ねた `<input>` が受け持つ(日本語入力・貼り付けが使える)。`NetGameScene` がやるので、ゲーム側は何もしない。
- フォントにない文字は、入力できない/「?」で表示される。

## 6. テスト・確認
- ゲーム側のアダプターは、偽の通信で確かめる: `tests/fakes.py`(偽の `Transport`)と、`tests/test_flow.py` `tests/test_tictactoe.py` の書き方が見本。`SDL_VIDEODRIVER=dummy` で、画面なしで動く。
- サーバー側のアダプターは、`server/testkit.js`(偽のソケット)で確かめる: `examples/tictactoe/adapter.test.js` が見本。`node --test`。
- 本物の Workers ランタイムでの通し確認: `npx wrangler dev` を起動して、2つの `NetGameScene` を本物の WebSocket でつなぐ(`examples/tictactoe/e2e.py`、`examples/pokoten/e2e_client.py`)。
- **ブラウザでの実機確認は、必ず別にやる**(Cloudflare のプレビューで、2つのブラウザ: ランダム・ルーム・チャット・再戦・退出)。

## 7. 更新するとき
netgame_fw を直して(PR → `main`)、ゲーム側で `copy_to_game.sh` をやり直し、テストを通し、フォントを作り直し、プレビューで確認する。通信のバージョン(`v`)が上がったら、サーバーとクライアントを同時に配信する(旧版のタブは、再読み込みが必要)。
