# アダプター: ゲームが書くもの

ゲームは「サーバー側のアダプター(JS)」と「クライアント側のアダプター(Python)」の2つだけを書く。
接続・名前・ルーム・準備OK・一時停止・チャット・結果・再戦・退出の流れは、フレームワークが動かす。
(以下は設計上のインターフェース。M1〜M3 で実装しながら調整する。)

## 1. サーバー側のアダプター(JS)

```js
// 共通
export default {
  id: "pokoten",                       // /ws?game=pokoten
  mode: "realtime",                    // "realtime" | "turns"
  minPlayers: 2, maxPlayers: 2,
  matchKey: (settings) => settings.diff,        // ランダムで組む条件(同じキーの人どうし)
  normalizeSettings: (s) => ({ diff: ["easy","normal","hard"].includes(s?.diff) ? s.diff : "normal" }),
  roomSettings: (host, guest) => host,          // ルームでは、作った人の設定に合わせる(既定)
  limits: { name: 8, chat: 30 },                // 既定から変えたいときだけ
};
```

### 1.1 realtime
```js
  events: {
    // k: { to: "others" | "none", validate(d) → bool, maxPerSec, on?(room, seat, d) }
    attack: { to: "others", validate: (d) => Number.isInteger(d.n) && d.n >= 1 && d.n <= 6, maxPerSec: 20 },
    snap:   { to: "others", validate: (d) => /^[.0-9]{144}$/.test(d.b) },
    over:   { to: "none",   on: (room, seat) => room.finish([{ seat, rank: 2 }, { seat: 1 - seat, rank: 1 }]) },
  },
```
- 登録のない `k` は、捨てる(`error: state`)。`validate` が `false` なら、捨てる。
- `room.finish(ranks, why)` で、結果を確定する(`result` を全員へ。状態は `over`)。
- クライアントの `finish`(`protocol.md` 4.3)を使うゲームは、`onFinish(room, seat, ranks)` で検証する。

### 1.2 turns(ロックステップ)
```js
  turns: {
    nextTurn: (room, seat, action) => (seat + 1) % room.players.length,   // 既定: 席の順
    validate: (room, seat, action) => true,    // 任意。ルールをサーバーでも確かめたいとき(通常は不要)
    maxActionBytes: 4096,
  },
```
- 手番の確認、`seq` の付与、中継、ハッシュの突き合わせ、`desync` は、フレームワークがやる。
- ルールはクライアントだけにある。サーバーは、手の中身を解釈しない。

## 2. クライアント側のアダプター(Python)

```python
from netgame import GameAdapter, GameConfig, NetGameScene

class PokotenAdapter(GameAdapter):
    config = GameConfig(id="pokoten", mode="realtime", min_players=2, max_players=2,
                        settings=lambda: {"diff": SETTINGS["difficulty"]})

    # --- 流れのフック(共通) ---
    def on_match(self, ctx):      # ctx.seed / ctx.you / ctx.players / ctx.settings。ゲームの用意をする
    def on_start(self):           # 全員が準備OK。カウントダウンが終わって、始まった
    def on_pause(self, paused):   # 一時停止/再開(チャット中)。効果音の停止などに
    def on_result(self, ranks):   # 結果が決まった(勝ち/負けの効果音など)
    def on_rematch(self):         # 新しい対戦の準備(on_match の前に呼ばれる)

    # --- 描画(共通。rect はフレームワークが決める) ---
    def draw_game(self, screen, rect, frame): ...
    def draw_side(self, screen, rect, frame): ...      # 右の列など(任意)
    def banner(self, state): ...                       # 帯の文言を上書きしたいとき(任意)

    # --- チャット(任意) ---
    def chat_templates(self): ...                      # テンプレート(既定は空。文言はゲーム側の strings)
    def chat_suggest(self, phase, ranks=None): ...     # 場面ごとに選択済みにするテンプレートの添字
```

### 2.1 realtime のフック
```python
    def update(self, frame):            # 毎フレーム。一時停止・カウントダウン中は呼ばれない
        self.game.update()
        for ev in self.game.drain_events():
            if ev["type"] == "clear":
                self.net.send_event("attack", {"n": 1})
        if self.game.over and not self.reported:
            self.net.send_event("over", {})
    def on_event(self, seat, kind, data):   # 他の席のイベントが届いた
        if kind == "attack": self.game.receive_garbage(data["n"])
        elif kind == "snap": self.opp_board = decode(data["b"])
```
- 入力は、ゲームが自分で受け取る(`handle_event(ev)` で、pygame のイベントが渡る)。チャット窓・確認ダイアログが開いている間は、渡されない。

### 2.2 turns のフック
```python
    def on_turn(self, seat, seq):             # 手番が回ってきた(seat == 自分なら、手を指せる)
    def on_action(self, seat, seq, action):   # サーバーから届いた手を適用する(自分の手も、ここで適用する)
        self.board.apply(seat, action)
    def state_hash(self) -> str:              # 適用後の状態のハッシュ(決定的であること)
        return sha1(self.board.serialize())
    def is_finished(self):                    # 終局なら ranks を返す(全員が同じ結果になること)
        return self.board.ranks() or None
    # 自分の手: self.net.send_action({"x": 1, "y": 2})   ← 手番でなければ、フレームワークが捨てる
```
- ルールは**決定的**にする。乱数は `ctx.seed` から作った `random.Random` だけ。浮動小数・`set` / `dict` の順序・並べ替えの安定性に依存しない。
- 手を送ったら、サーバーから `on_action` が返るまで、自分の盤面は変えない(全員が同じ順で適用するため)。

## 3. 画面の設定(Theme / Strings)
```python
scene = NetGameScene(PokotenAdapter(), screen_size=(480, 800),
                     theme=Theme(bg=..., accent=..., font=jp_font),
                     strings=Strings.ja(extra={...}))      # 文言を上書き・追加
```
- `Theme`: 配色・ボタンの見た目・フォントの取得関数。画面サイズに合わせた配置は、フレームワークが計算する。
- `Strings`: 日本語の既定。文言を足したら、`tools/build_font.py` でフォントを作り直す(ゲームの文言も、渡して一緒に)。
- 画面部品を個別に使うこともできる(`ui.NameField` / `ui.Keypad` / `ui.ChatPanel` / `ui.ResultButtons` など)。

## 4. ゲームが受け取るもの(`self.net`)
- `send_event(kind, data)` / `send_action(action)` / `report_finish(ranks)` / `chat(text)`
- `players`(席・名前)/ `you`(自分の席)/ `seed`
- `paused`(いま止まっているか)/ `frozen`(チャット中・カウントダウン中のどちらでも `True`)
