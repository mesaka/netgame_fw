# アダプター: ゲームが書くもの

ゲームは「サーバー側のアダプター(JS)」と「クライアント側のアダプター(Python)」の2つだけを書く。
接続・名前・ルーム・準備OK・一時停止・チャット・結果・再戦・退出の流れは、フレームワークが動かす。
(1.1 / 1.2 は v1、1.3 は v2。いずれも実装済み。)

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

### 1.3 authoritative(サーバー権威型。v=2)
```js
export default {
  id: "cards", mode: "authoritative", minPlayers: 2, maxPlayers: 2,
  matchKey: () => "all",
  flow:  { ready: false, rematch: "game" },       // 省略時: { ready: true, rematch: "framework" }
  rooms: { code: "alnum4", password: "none" },    // 省略時: { code: "digits6", password: "required" }
  events: { stamp: { to: "others", maxPerSec: 3, validate: (d) => Number.isInteger(d.id) } },   // 任意
  game: {
    init(ctx)                      { return state; },                // 新しい対戦の状態(JSON にできる値)
    startEvents(state, ctx)        { return [{ t: "deal" }]; },      // 任意。最初の state に付く events
    apply(state, seat, action, ctx){ return { ok: true, events: [] }; },   // 状態を直接変えてよい。断るなら { ok: false, error: "理由" }
    view(state, seat)              { return { /* その席から見える範囲だけ */ }; },
    outcome(state)                 { return null; /* 終わりなら { ranks: [{seat, rank}], why? } */ },
    eventsFor(state, seat, events) { return events; },               // 任意。席ごとに events を変える(隠し情報があるとき)
  },
};
```
- `onLeave: { grace: 60, then: "forfeit" }`(任意): 切断してから退出とみなすまでの猶予(秒。既定 60。`0` でなし)と、猶予切れ・退出のときの扱い(`forfeit`: 残りの人の勝ち / `abort`)。猶予のあいだは、`resume` で同じ席に戻れる(`protocol.md` 9.5)。
- `ctx` = `{ roomId, settings, players: [{seat, name}], seed, rng }`。**乱数は `ctx.rng()` だけ**を使う(部屋の seed から作る決定的な乱数。Durable Object が休止しても、続きの位置が保たれる)。`Math.random` を使わない。
- `state` は、**JSON にできる値**にする(関数・`Map`・`Set`・循環を入れない)。`apply` の成功のたびに、サーバーが保存する。`apply` が断った(`ok: false`)・例外を投げたときは、保存しない(状態は変わらない)。
- `apply` は、手番・手の形・ルールを**すべて自分で確かめる**(サーバーは、手の中身を解釈しない)。
- `outcome` は、手のたびに呼ばれる。「続く」→「終わり」に変わったとき、1回だけ `result` になる(`ranks` が全員分でなければ無視)。
- 見本: `examples/cards/adapter.js`(隠した手札・スタンプ・結果のあとの「もう一度」)。テスト: `server/authoritative.test.js`。

## 2. クライアント側のアダプター(Python)

画面の流れ(名前・ルーム・準備OK・カウントダウン・チャット・結果・退出)は `NetGameScene`(`client/netgame/flow.py`)が受け持つ。ゲーム側は `GameAdapter` を継承して、対戦中の「動かす・描く」だけを書く(M3 で実装した形。`docs/ui.md`)。

```python
from netgame.adapter import RealtimeAdapter, TurnAdapter    # どちらかを継承する
from netgame.flow import NetGameScene

scene = NetGameScene(MyAdapter(), theme=Theme(font=...), strings={"net_title": "..."})
# 毎フレーム: scene.handle(ev) / r = scene.update()(r == "menu" ならタイトルへ)/ scene.draw(screen)
```

### 2.1 共通(GameAdapter)
```python
    game_id = "pokoten"         # サーバーのアダプターと同じ ID
    size = (480, 800)
    sess                        # 通信(NetSession)。NetGameScene が入れる。seed / players / seat / settings / opp_name など
    def settings(self) -> dict          # register に載せる設定(ランダムマッチは、同じ設定の人どうし)
    def settings_label(self) -> str     # 名前入力・待機画面に出す設定の説明
    def start_match(self, sess)         # 新しい対戦(match)。sess.seed / sess.players / sess.seat で初期化する
    def reset_input(self)               # 入力を離す(チャットの窓を開いたときなど)
    def handle(self, ev)                # 対戦中の入力。チャット入力中・確認中は呼ばれない
    def update(self, sess, controls)    # 1フレーム。一時停止・カウントダウン・再開待ちの間は呼ばれない
    def local_over(self) -> bool        # 自分の側が終わったか(帯の表示用)
    def draw(self, sess, screen, view, frame)   # view.banner = (大きい字, 色, 小さい字)。盤面に重ねて出す
    def draw_top(self, screen)          # 一番手前(エフェクトなど。任意)
    def handle_global(ev, phase) / draw_global(screen, phase)   # 音量ボタンなど(任意)
    def sound(name) / bgm(name)         # 音(任意)
    def load_name() / save_name(name)   # 名前の保存(既定: ブラウザの localStorage)
```

### 2.2 realtime(RealtimeAdapter)
```python
    def update(self, sess, controls):
        for _, kind, d in sess.take_events():          # 他の席のイベント
            if kind == "attack": self.garbage += d["n"]
            elif kind == "snap": self.opp_board = decode(d["b"])
        self.game.update()
        for ev in self.game.events:
            if ev["type"] == "clear": sess.send_event("attack", {"n": 1})
        if self.game.over and not self.reported:
            sess.send_event("over")                    # サーバーのアダプターの over が、勝敗を決める
```
- 実例: ポコテンの `PokotenAdapter`(mesaka/pokoten の `main.py`)。

### 2.3 turns(TurnAdapter)
```python
class MyTurnGame(TurnAdapter):
    def on_match(self, sess):                 # 新しい対戦の用意
    def on_action(self, seat, seq, action):   # サーバーから届いた手を適用する(自分の手も、ここで適用する)
    def state_hash(self) -> str:              # 適用後の状態のハッシュ(64文字まで・決定的)。self.digest(obj) が使える
    def is_finished(self):                    # 終局なら ranks([{"seat","rank"}])、まだなら None
    # 入力・描画: handle(ev) で self.play(self.sess, {"cell": 3}) / draw(...)
```
- `TurnAdapter.update` が、届いた手を順に適用して、ハッシュ(`sync`)を送り、終局になったら結果を申告(`finish`)する。同じ手(seq)が二度届いても適用しない。
- 手番でなければ、`play` は送らない(`False`)。手を送ったら、`on_action` が呼ばれるまで、自分の盤面は変えない(全員が同じ順で適用するため)。
- ルールは**決定的**にする。乱数は `sess.seed` から作った `random.Random` だけ。浮動小数・`set` / `dict` の順序・並べ替えの安定性に依存しない。サーバーは手の中身を見ないので、**不正な手(空いていないマスなど)は、全員が同じように無視する**ルールにする(○×の `ttt_rules.py` が例)。
- チャットで止まっている間(`frozen`)は `update` が呼ばれず、届いた手は溜まって、再開後に順に適用される。
- ハッシュが食い違うと、サーバーが `desync` を送って対戦を中止する(結果は全員1位・`why: "desync"`)。画面は「状態がずれたため、中止しました」と出す。
- 実例: `examples/tictactoe/`(○×。サーバー側 `adapter.js`・ルール `ttt_rules.py`・クライアント `ttt_client.py`)。3人用のサーバー側の見本は `examples/guess3/`(数当て)。

## 3. 画面の設定(Theme / Strings)
```python
scene = NetGameScene(MyAdapter(), theme=Theme(font=jp_font, background=draw_background),
                     strings={"net_title": "ネット対戦"})      # 文言を上書き・追加(既定は strings_ja.py)
```
- `Theme`: 色・ボタンの見た目・フォント(`font(size)`)・背景(`background(screen)`)。画面サイズに合わせた配置は `Layout` が計算する(基準 480×800 を中央に置く)。
- `Strings`: 日本語の既定。文言を足したら、ゲーム側のフォント作成をやり直す(`netgame/strings_ja.py` の文字も入れる)。
- 画面部品(`ui/screens.py` `ui/widgets.py`)を、個別に使うこともできる。
