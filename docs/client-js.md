# JS クライアント(`client-js/netgame/client.js`)

ブラウザ(JS)のゲーム向けの、**通信と状態管理だけ**のクライアント。画面(DOM・canvas)は含まない。依存なし(ESM 1ファイル)。ブラウザと Node 22 以上で動く。
Python クライアント(`client/netgame/session.py`)と**同じプロトコル(`protocol.md`)の、別実装**。再接続・登録時の扱い・状態の解釈は、2つで同じ振る舞いにしてある(違いは、下の「Python クライアントの v=2」に書いた3点だけ)。同じ解釈をすることは、適合テストで確かめている(下の「適合テスト」)。

対応: v=1(realtime / turns)も v=2(authoritative・再接続)も扱える。新しいゲームは、v=2 の authoritative を勧める(隠し情報を守れ、再接続できる)。

## 取り込む
```
bash tools/copy_js_client.sh <ゲームのフォルダ>/js/netgame      # client.js / LICENSE / NOTICE / SOURCE_COMMIT がコピーされる
```
コピーしたものは直接直さない(直すなら netgame_fw で直して、もう一度コピー)。**出典の記載が条件**(README の「出典の書き方」)。

## 使いかた
```js
import { NetGameClient } from "./netgame/client.js";

const net = new NetGameClient({
  url: "wss://example.com/ws",     // ?game=&v= は付けなくてよい
  game: "awase", v: 2,
  storage: localStorage,           // token と部屋コードの保存先(省略可。ページを開き直しての再接続に要る)
  reconnect: { minMs: 1000, maxMs: 10000 },   // 自動再接続(false で無効)
});

net.on("state", async ({ view, events, resync }) => {   // Promise を返せば、完了まで次の通知を待つ(アニメーション用)
  if (resync) renderNow(view); else await animate(events, view);
});
net.on("presence", ({ seat, online }) => {});
net.on("result", ({ ranks, why }) => {});
net.on("status", (s) => {});                 // "connecting" | "open" | "reconnecting" | "closed"
net.on("resume_failed", () => {});           // 戻れなかった(猶予切れなど)。登録しなおせる

await net.connect();                         // hello が届くまで待つ(失敗なら reject。net.error に理由)
if (!net.resume()) net.registerRandom({ name: "ゲスト", settings: { rounds: 3 } });   // 保存した token があれば戻る
// 友だちと: net.registerFriend({ name, settings })(部屋を作る。net.room が部屋コード)/ net.registerFriend({ name, room: "AB3X" })

net.act({ type: "play", card: 3 });          // 手。結果は state で届く(自分の盤面は、それまで変えない)
net.event("stamp", { id: 2 });               // 他の席へ中継(アダプターの events に登録のあるもの)
net.say("よろしく");                          // チャット(履歴は net.chat)
net.leave();                                 // 部屋を出る(すぐ退出。保存した token も消す)
net.close();                                 // 接続だけ閉じる(猶予のあいだ、席は残る。自動再接続はしない)
```

### 状態(読み取り)
`phase`(`connecting` → `idle` → `waiting` → `ready` → `playing` → `over` / `resuming` / `closed`)、`seat`、`players`、`room`、`token`、`config`、
`view`・`seq`・`events`・`resync`(authoritative の最新の state)、`result`、`offline`(切断中の席)、`relayed`(他の席から中継されたイベント)、`chat`、`errors`、`ruleErrors`。
`snapshot()` は、その一覧(token と部屋コードの中身を含まない)。

### 通知(`on`)
`hello` `registered` `waiting` `match` `ready_state` `start` `state` `result` `presence` `resumed` `event` `chat` `paused` `action` `turn` `desync` `rematch_req` `player_left` `error` `resume_failed` `status`。
`on` は、登録を外す関数を返す。ハンドラーの例外は、ほかの処理を止めない(`console.error`)。

### 再接続
- 通信が途切れたら、自動でつなぎ直し(間隔 `minMs` から `maxMs` まで少しずつ延びる。±25% のゆらぎ)、新しい接続の `hello` のあとに `resume`(部屋コード + token)を送って、同じ席に戻る。戻ったら `resync: true` の `state` が届く。
- 再接続しているあいだ(`status === "reconnecting"`)の送信(`act` など)は、**古い盤面への操作になるので送らず、`false` を返す**。最初の接続が終わる前の送信だけ、つながるまでためる。
- 戻れなければ(部屋がない・合言葉が違う・猶予切れ)、`resume_failed` を通知し、保存した token を消し、`phase` は `idle`(登録しなおせる)。
- `giveUpMs`(既定 5 分)のあいだ再接続できなければ、`closed`(`error: "lost"`)。
- token と部屋コードは `storage`(`netgame.<game>`)に保存される。ページを開き直したら、`connect()` のあとに `resume()` を引数なしで呼ぶ。
- 明示の `leave()` は、猶予なしの退出(相手の勝ち)。`close()` は、ただの切断(猶予のあいだ席が残り、`resume` で戻れる)。

### 順序
受信は、届いた順に、1件ずつ処理する(`close` も同じ列)。`state` のハンドラーが Promise を返したら、完了まで次の通知(次の `state` や `result`)を待つ。`idle()` は、いま溜まっている処理がすべて終わるまで待つ Promise。

## v=1(realtime / turns)で使う
`action(seq, d)` / `sync(seq, hash)` / `finish(ranks)` / `pause(on)` / `ready()` / `rematch()` も用意してある(Python の `NetSession` と同じ意味)。再接続(`resume`)は authoritative だけ。

## Python クライアントの v=2
`NetSession(transport, game, version=2)`(`client/netgame/session.py`。画面部品 `flow.py` は v1 だけを使う)。**JS 版 `NetGameClient` と同じ振る舞い**。
```python
sess = NetSession(make_transport(), "awase", version=2)    # reconnect=False で自動再接続を止める / transport_factory=… で新しい接続の作りかたを変える
sess.start()
# 毎フレーム sess.update()(受信・時間の経過・再接続がここで進む)。state が "idle" になったら:
if not sess.resume(room, token):                    # 保存しておいた部屋コード + token があれば、戻る
    sess.register("ゲスト", mode="random")          # 友だち: mode="friend"(room なし = 作る / room あり = 入る)
sess.act({"type": "play", "card": 3})               # authoritative の手。送れたら True(再接続のあいだは False)
for seq, view, events, resync in sess.take_views(): ...      # 届いた state(resync なら、アニメーションせず置き換える)
```
- **自動再接続**(JS 版と同じ): 通信が途切れたら、`status` が `"reconnecting"` になり(`state` は切れる前のまま)、待ち時間(`min_ms` 1秒から `max_ms` 10秒まで×1.3ずつ、±25% のゆらぎ)のあとに新しい接続を開く。新しい接続の `hello` が届くと `resume` を送り、戻れたら `resync` の `state` が届く。
  - 再接続のあいだ(`hello` が届くまで)は、`act` / `say` / `send_event` などは**送らず、`False` を返す**。
  - 戻れなければ(`error: resume`)、`state` は `"idle"`、`notice` は `"resume"`、token と部屋コードは空、対戦の状態は空になる(登録しなおせる)。
  - `give_up_ms`(既定 5 分)のあいだ戻れなければ、`state == "closed"`・`error == "lost"`。
  - 設定: `reconnect={"min_ms":…, "max_ms":…, "factor":…, "give_up_ms":…}`(一部だけでよい)。`False` で無効。`close()` のあとは、再接続しない。部屋に入る前(token も部屋コードもない)に切れたときは、再接続せず `"closed"`(`error == "lost"`)。
  - 時計は、`NetSession(..., clock=…)` で差し替えられる(テスト用)。
- **登録時の扱い**(JS 版と同じ): 名前は整えて(制御文字を除き、前後の空白を削り、上限の文字数に切る)、空なら送らない。**合言葉と部屋コードは検査せず、そのまま送る**。形・要否はゲームの設定(`rooms`)しだいなので、サーバーが検査して、`error`(`key` / `room` / `pass` など)で返す。そのとき `state` は `"idle"` に戻り、`notice` に理由が入り、`errors` にも残る(やり直せる)。v=1 は、これまで通り、送る前に検査する。
- **まだ違うところ**(JS 版にあって Python 版にないもの):
  - token と部屋コードの**保存**(JS 版は `storage`。ページを開き直しても戻れる)。Python 版は、保存先を持たない。呼び出し側が、`sess.token` と `sess.room_code` を保存して、`resume(room, token)` に渡す。
  - `leave()`(部屋を出る)。Python 版は `close()` で閉じる(猶予のあいだ席が残る)。
  - `connect()` の Promise(Python 版は `start()` のあと `update()` で `state` が `"idle"` になるのを見る)。

## 適合テスト(`tests/conformance/`)
2つのクライアントが、同じサーバーの出力を、同じ状態として解釈することの確認。

- `scenario.json`: 手順(接続 → ランダムマッチ → 手 → ルール違反 → スタンプ → チャット → 切断 → resume → 最後まで → **通信が途切れて自動再接続** → **登録の失敗(部屋がない・形の悪い入力)** → 部屋コード対戦 → 猶予切れ → **戻れない**)。
- `golden.json`: 各ステップのあとの `snapshot()`(JS と Python で同じ形)。
- JS: `client-js/conformance.test.js`(サーバーの核と同じプロセスで)。Python: `tests/test_conformance.py`(Node の `host.mjs` が動かすサーバーの核に、標準入出力でつなぐ)。どちらも、同じ決定的な世界(`world.mjs`: 固定の乱数・偽の時計)に同じ手順を実行し、golden と一致することを確かめる。
- 通信の仕様やサーバーの挙動を変えて golden が変わるときは、`UPDATE_GOLDEN=1 npm test` で作り直し、**差分を見て、意図したものか確認する**。
- 新しいクライアント(別の言語など)を作るときも、同じシナリオを通せば、同じ解釈であることを確かめられる。
