# 画面部品の使い方(`client/netgame/flow.py` と `ui/`)

対戦の前後の画面(名前・ルーム・待機・準備OK・カウントダウン・チャット・結果・退出)は `NetGameScene` が受け持つ。ゲームが書くのは、対戦中の「盤面を動かす・描く」だけ(アダプター)。

```python
from netgame.adapter import RealtimeAdapter
from netgame.flow import NetGameScene

class MyAdapter(RealtimeAdapter):
    game_id = "mygame"            # サーバーのアダプターと同じ ID
    size = (480, 800)

    def settings(self):            return {"diff": "normal"}    # register に載る。ランダムマッチは同じ設定の人同士
    def settings_label(self):      return "むずかしさ: ふつう"
    def start_match(self, sess):   ...   # sess.seed / sess.players / sess.seat で初期化
    def update(self, sess, controls): ...  # 1フレーム進める。controls=False なら操作は受けない。イベントは sess.send_event(...)
    def draw(self, sess, screen, view, frame): ...  # 盤面・得点・相手の様子。view.banner は盤面に重ねて出す
    def handle(self, ev):          ...   # ゲームの入力(キー・タッチ)
    def reset_input(self):         ...   # 押しっぱなしを離す
    def local_over(self):          return False
    # 任意: draw_top(エフェクト) / handle_global・draw_global(音量ボタンなど) / sound・bgm / load_name・save_name

scene = NetGameScene(MyAdapter())           # theme=Theme(font=...), strings={"net_title": "..."} で見た目・文言を差し替え
# 毎フレーム: scene.handle(ev) / r = scene.update() / scene.draw(screen)。r == "menu" なら、タイトルへ戻る
```

## 受け持ち
| 部品 | 受け持ち |
|---|---|
| `NetGameScene`(`flow.py`) | 画面の流れ全体・通信(`NetSession`)・入力(PC のキー・IME・貼り付け / ブラウザの入力欄)・チャットで止める・カウントダウン・再開待ち・退出の自動処理 |
| `GameAdapter`(`adapter.py`) | ゲームの盤面・操作・得点・相手の様子・音 |
| `Theme` | 色・フォント(日本語が出るもの)・背景 |
| `Strings` | 文言(既定は日本語。キーは `strings_ja.py`)。文字を足したら、ゲーム側のフォント作成をやり直す |
| `Layout` | 置き場所。基準 480×800 を、大きい画面の中央に置く |

アダプターが受け取る音の名前: `menu_ok` / `menu_move`(相手のチャットが届いた)/ `win` / `lose`。BGM: `menu`(対戦の前後)/ `game`。

## 確認
- `python -m pytest tests/test_flow.py` — 偽の通信での流れのテスト。
- `python tools/compare_pokoten.py --pokoten <ポコテンの場所> [--out DIR]` — ポコテンの現行の画面と、ピクセル単位で見比べる(`--out` に並べた画像を書き出す)。

ターン制のゲームは `TurnAdapter` を継承する(`docs/adapter.md` 2.3、見本は `examples/tictactoe/`)。流れ(`NetGameScene`)は、リアルタイム制と同じ。
