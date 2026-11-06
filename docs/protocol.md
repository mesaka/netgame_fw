# 通信プロトコル v1

WebSocket のテキストフレーム。1フレーム = 1つの JSON オブジェクト(`t` が種類)。
クライアント → サーバーは、ASCII だけの JSON(`\uXXXX` のエスケープ)で送る。サーバー → クライアントも、ブラウザ側の橋渡しが ASCII に直して渡す。
生存確認: クライアントが文字列 `ping` を送ると、サーバー(Durable Object を起こさずに)`pong` を返す。20秒おきに送る。

接続先: `/ws?game=<ゲームID>&v=<版>`。版は `1`(省略時)か `2`(9 章)。ゲームIDが未登録・版が合わない・`authoritative` のゲームに v=1 で来た場合は、`error`(`code: "game"` / `"version"`)を送って閉じる。
**v=2 は、v=1 への追加だけ**で、v1 のメッセージの意味は変わらない(9 章で足すもの以外)。

## 1. 用語
- **接続ID** `id`: サーバーが接続ごとに発行する識別用の文字列(`K7M2-QX9P` 形式)。画面には出さない。内部の識別に使う。
- **席** `seat`: 部屋の中の番号(0 始まり)。2人なら 0 と 1。
- **ルームID**: ルーム方式で、サーバーが発行する6桁の数字。**パスワード**: 作る人が決める4桁の数字。
- **mode**: ゲームの方式。`"realtime"` または `"turns"`(ゲームごとに固定。`hello` で通知)。
- **設定** `settings`: 組み合わせの条件になるゲーム固有の値(例: ポコテンの `{"diff": "normal"}`)。サーバーのアダプターの `matchKey(settings)` で、組み合わせのキーにする。

## 2. 部屋の状態

```
(接続) new ─register→ waiting ─(相手がそろう)→ ready ─(全員 ready)→ playing ─(結果)→ over
                                                  ↑                                      │
                                                  └──────────── rematch(全員)───────────┘
```
- 切断・`leave` は、どの状態でも起きる。2人対戦では、`playing` / `ready` の最中の退出は「残りの人の勝ち」(`why: "left"`)、`over` のあとの退出は `player_left` を知らせるだけ。
- 3人以上の退出方針(`forfeit` / `continue` / `abort`)は、将来の拡張。席と `player_left` の形は、そのまま使える。

## 3. クライアント → サーバー

| t | 中身 | いつ | 説明 |
|---|---|---|---|
| `register` | `name`, `mode`, `settings`, `room?`, `pass?` | `new` | 名前を登録して、相手をさがす。`mode`: `"random"` / `"friend"`。friend で `room` なし = 部屋を作る(`pass` 必須)。`room` と `pass` あり = 入る |
| `ready` | | `ready` | 準備OK。全員が送ると `start` |
| `pause` | `on` (bool) | `playing` | チャットの入力・選択中は `true`。誰かが `true` の間、全員のゲームを止める |
| `event` | `k`, `d` | `playing`(realtime) | ゲームのイベント。`k` は、アダプターに登録した種類。`d` は中身(JSON)。他の席へ中継される |
| `action` | `seq`, `d` | `playing`(turns) | 手。手番の席だけ。`seq` は、いま期待されている通し番号 |
| `sync` | `seq`, `h` | `playing`(turns) | 手を適用したあとの状態のハッシュ(文字列、64文字まで)。全員の分を突き合わせる |
| `finish` | `ranks`, `why?` | `playing` | ゲームが終わったと申告する(結果の確定は、サーバーのアダプターの規則に従う。4.3) |
| `chat` | `text` | `ready` / `playing` / `over` | 全角30文字まで。連投は0.4秒おき |
| `rematch` | | `over` | もう一度。全員が送ると、新しい `match` |
| `leave` | | 任意 | 自分から部屋を出る(切断と同じ扱い) |

## 4. サーバー → クライアント

| t | 中身 | 説明 |
|---|---|---|
| `hello` | `id`, `v`, `game`, `config` | 接続できた。`config` = `{min_players, max_players, mode, limits}` |
| `registered` | `id`, `name` | 登録できた |
| `waiting` | `room?` | 相手を待つ。ルームを作った人には、発行した `room`(ルームID) |
| `match` | `seed`, `you`, `players`, `settings`, `mode` | 部屋が決まった。`players` = `[{seat, name}]`。準備中の状態になる |
| `ready_state` | `seats` | 準備OKを押した席の一覧(押すたびに全員へ) |
| `start` | `turn?` | 全員が準備OK。カウントダウンを始めてよい。turns なら、最初の手番 `turn` = `{seat, seq: 0}` |
| `paused` | `seat`, `on` | その席が、止めた/再開した |
| `event` | `seat`, `k`, `d` | 他の席のイベント(realtime) |
| `action` | `seat`, `seq`, `d` | 手(turns)。**送った本人にも返る**(全員が、サーバーが決めた順で適用する) |
| `turn` | `seat`, `seq` | 次の手番 |
| `desync` | `seq` | ハッシュが食い違った(中止になる。`result` の `why: "desync"` が続く) |
| `result` | `ranks`, `why` | 結果。`ranks` = `[{seat, rank}]`(1が勝ち。同順位あり)。`why`: `"normal"` / `"left"` / `"desync"` / `"abort"` |
| `chat` | `seat`, `name`, `text` | チャット(送った本人にも返る) |
| `rematch_req` | `seat` | その席が「もう一度」を押した |
| `player_left` | `seat` | その席が退出した(対戦が終わっているとき) |
| `error` | `code`, `d?` | エラー |

### 4.1 エラーコード
`name`(名前が空) / `key`(パスワードが4桁の数字でない) / `room`(ルームがない・満員・対戦中・間違いが続いて閉じた) / `pass`(パスワードが違う) / `game`(未登録のゲーム) / `version`(版が違う) / `rate`(送りすぎ。部屋に入る失敗が続いたときは `d: {retry_ms}`) / `state`(いまの状態では送れない) / `rule`(v=2。`act` がゲームのルールで断られた。`d` に理由) / `resume`(v=2。再接続できない。部屋がない・合言葉が違う・猶予切れ、は区別しない)。
登録に関するエラー(`name` `key` `room` `pass`)は、登録されないまま、やり直せる。

### 4.2 ルームのパスワード
4桁(1万通り)は総当たりできるため、**1つの部屋で5回間違えたら、その部屋は閉じる**(`room` を返す。作り直す)。

### 4.3 結果の確定
- **realtime**: アダプターが、イベントを受け取ったとき、または `finish` を受け取ったときの規則で、`ranks` を決める(例: ポコテンは、最初に `over` を送った席が負け)。確定したら、`result` を全員へ送り、状態を `over` にする。
- **turns**: 全員の `finish` の `ranks` が**一致**したら確定する。食い違えば `desync`。手の検証をサーバーでもしたい場合は、アダプターの `validate`(任意)で行う。
- 対戦中の退出は、`result`(`why: "left"`)で、残りの席の勝ち(2人の場合)。

## 5. ターン制(turns)の流れ

```
start {turn:{seat:0, seq:0}}
  手番の席:  action {seq:0, d:...}
  サーバー:  (手番・seq を確認 → 全員へ) action {seat:0, seq:0, d:...} → turn {seat:1, seq:1}
  全員:      sync {seq:0, h:"..."}   ← 手を適用した後のハッシュ
  サーバー:  全員の h が一致 → 何もしない / 食い違い → desync
  ...
  終局を検出した全員: finish {ranks:[...]}  → 一致したら result
```
- 手は、**サーバーから届いた順に**適用する(自分の手も、`action` が返ってから適用する)。これで、全員の適用順が同じになる。
- 手番ではない席の `action`、`seq` が違う `action`、大きさが上限(既定 4KB)を超える `action` は、`error`(`state` / `rate`)で捨てる。
- 次の手番は、アダプターの `nextTurn(room, seat, action)`(既定: 席の順に回す)。
- 手の記録(`seq` 順の列)は、部屋の Durable Object が持つ(再接続・途中からの再現は、v2)。
- 隠し情報(手札など)は、v1 では扱えない(全員が `seed` と全手を知る)。

## 6. 一時停止
- `pause {on:true}` を送った席を、部屋の「止めている席の集合」に入れ、全員へ `paused {seat, on}` を送る。集合が空でなければ、全員がゲームの時間(realtime の更新・カウントダウン・持ち時間)を止める。
- 止めっぱなしの対策として、クライアントは、自分の止めを30秒で自動的に解除し、他の席の止めも40秒で無効にする。

## 7. 制限の既定(`hello` の `config.limits` で通知。ゲームで変更可)
| 項目 | 既定 |
|---|---|
| 名前 | 8文字 |
| チャット | 30文字・0.4秒に1回 |
| `event` / `action` の大きさ | 4KB |
| 受け取る1フレームの大きさ | 8KB |
| パスワードを間違えられる回数 | 5回 |

## 8. 将来の拡張(予約)
- 3人以上: `match.players` が3つ以上。ルームの「開始」(`start_room`)、人数がそろうまでの待ち、退出時の方針。
- 再接続: `register` に `resume` トークン。サーバーが手の記録を再生する。
- 観戦: `role: "spectator"`。
- ターン制の持ち時間: Durable Object のアラームで、時間切れを確定する。

## 9. v2(`v=2`): サーバー権威型・部屋と進行の設定

設計の背景は `design-v2.md`。実装は `server/core.js`、見本は `examples/cards/`(本物の Workers での確認: `examples/cards/e2e.mjs`)。
**状態: M9 まで実装済み**(再接続 `resume`・`presence`・切断の猶予は 9.5)。

### 9.1 hello(v=2)
v=2 の `hello` の `config` に、次が加わる(v=1 には足さない)。
- `flow`: `{ready, rematch}`。`ready: false` = 全員の `ready` を待たず、部屋が決まったらすぐ `start`。`rematch: "game"` = 結果のあとの進行はゲームの手で行い、`rematch` メッセージは使わない。
- `rooms`: `{code, password}`。`code`: `"digits6"`(6桁の数字)/ `"alnum4"`(紛らわしい文字を除く英数4文字。入力は大文字小文字を区別しない)。`password`: `"required"`(4桁の数字)/ `"optional"` / `"none"`。

### 9.2 `register`(friend)の変更
- `password: "none"`: `pass` は不要(あっても無視)。`"optional"`: 送れば、その部屋に合言葉がつく(4桁の数字)。合言葉のある部屋には、一致する `pass` が要る。ない部屋は、なしで入れる。
- 部屋に入る失敗(部屋がない・満員・合言葉違い)が、**5回続くと60秒、入れない**(`error: rate`, `d: {retry_ms}`)。数えるのは、接続元(Cloudflare の接続元 IP。接続し直しても続く)。接続元が分からないときは、接続ごと。成功すると数え直す。
  - **適用するゲーム**: `password` が `"none"` / `"optional"` のゲーム(既定。アダプターの `rooms.joinLimit` で変えられる)。`"required"`(v1 の既定)は、これまで通り、部屋ごとの間違い回数(`passFails`)だけ。
  - 回数と時間は、アダプターの `limits.joinFails` / `limits.joinBlockMs`。

### 9.3 authoritative(`mode: "authoritative"`)
ルールとゲームの状態は、サーバーだけが持つ(クライアントは手を送るだけ)。**v=2 でだけ使える。**

状態遷移は、v1 と同じ(`waiting` → `ready` → `playing` → `over`)。ただし `flow.ready: false` なら `ready` を飛ばして、`match` の直後に `start`。

| 方向 | t | 中身 | 説明 |
|---|---|---|---|
| C→S | `act` | `a`(手。JSON。大きさは `actionBytes` まで) | 手。サーバーが、ゲームの `apply` で検証して適用する |
| C→S | `resync` | | 自分の最新の view を、もう一度送ってほしい |
| S→C | `state` | `seq`, `view`, `events`, `resync?` | 状態が変わるたびに、各席へ、**その席の view** を送る。`seq` は、対戦ごとに 0 から、1ずつ増える |
| S→C | `error` | `code: "rule"`, `d` | `act` が断られた(`d` = ゲームが返した理由)。**直後に**、本人にだけ最新の `state`(`resync: true`)が届く。状態は変わらない |

- `start` の直後に、`state`(`seq: 0`)が届く(`events` は、ゲームの `startEvents`。「配った」など)。
- `state.events` は、アニメーションなどのための、ゲームが決めた出来事。既定では全席に同じものを送る(ゲームが、席ごとに変えることもできる)。
- `state.view` は、**その席から見える範囲だけ**(相手の手札などは含まれない)。席ごとに内容が違う。
- 手の検証は、すべてサーバー(`apply`)。手番でない席・ルール違反の手は `error: rule`。サーバーが落ちるような手も、`rule`(`d: "exception"`)で断り、状態は壊れない。
- `resync: true` の `state` は、全体の送り直し。クライアントは、アニメーションをせず、その view で盤面を置き換える。
- **結果**: ゲームの `outcome` が「続く」から「終わり」に変わったとき、1回だけ `result` が届く。
  - `flow.rematch: "framework"`(既定): `result` のあと `over`(v1 と同じ。`rematch` で次の対戦)。
  - `flow.rematch: "game"`: **部屋は `playing` のまま**。`result` は通知だけで、そのあとも `act` を受ける(ゲーム内の「もう一度」など)。次に「終わり」になれば、また1回 `result`。
- 退出は、v1 と同じ(対戦中に `leave` すると、残りの人の勝ち `why: "left"`)。**切断は、猶予をおいてから退出になる**(9.5)。
- `chat` / `pause` / `leave` は、v1 と同じ。

### 9.4 `event`(中継)の拡張
`authoritative` と `turns` でも、アダプターが `events` を定義していれば、`event` で中継できる(スタンプなど)。定義のない `k` は `error: state`。ただし、`events` を持たない `turns` のゲーム(v1)は、これまで通り `event` を無視する。

### 9.5 再接続(resume)・切断の猶予・presence(`authoritative` のみ)

**token と部屋コード**
- v=2 の authoritative では、`registered` に `token`(席の合言葉。32桁の16進。サーバーが発行)が付く。クライアントは、**保存しておく**(画面には出さない。他の人には送られない)。
- `match` に `room`(部屋コード)が付く(v=2 のみ)。ルームを作った・入った人は、`waiting` / `match` の `room` で分かる。
- 再接続に要るのは、**部屋コード + token**。

**切断の猶予**
- 切断(ソケットが閉じる)しても、すぐには退出にならない。その席を「切断中」にして、他の席へ `presence {seat, online: false}` を送る。対戦は、残った人の手で続けられる(手番を待つなど、ゲームの決めたまま)。
- 猶予は、アダプターの `onLeave: { grace: <秒>, then: "forfeit" | "abort" }`。**既定は 60 秒**。`grace: 0` なら、切断もすぐ退出(v1 と同じ)。
- 猶予が切れたら(Durable Object のアラームで判定)、退出として扱う(対戦中なら `result` `why: "left"`、待機中の部屋なら部屋が消える)。
- 明示の `leave` は、猶予なしですぐ退出。
- 待機中(相手がまだいない)の部屋の作成者が切れたときも、猶予のあいだは部屋が残る(友だちは、そのあいだに入れる)。

**resume**
```
C→S  {t:"resume", room:"AB3X", token:"…"}        新しい接続(状態は new)から
S→C  {t:"resumed", id, you, room, status, mode, settings, seed, players:[{seat,name}]}
       status = 部屋の状態: "waiting" | "ready" | "playing" | "over"
     続けて、状態に応じて:
       playing → {t:"state", resync:true, seq, view, events:[]}     いまの自分の view
       ready   → {t:"ready_state", seats}
       waiting → {t:"waiting", room}
       over    → {t:"result", ranks, why}
     切断中の他の席があれば、席ごとに {t:"presence", seat, online:false}
他の席へ  {t:"presence", seat, online:true}
```
- 失敗は `error: "resume"` 1種類(部屋がない・合言葉が違う・猶予切れ・別のゲーム)。理由を区別しない。
- 切れたことにまだ気づいていない古い接続が残っていたら、`resume` でその接続を閉じて(close コード 4001 `replaced`)入れ替える。古い接続の close は、あとで届いても無視される。
- token は、その席が退出するか、部屋が消えるまで有効。
- resume で戻った人は、`resync: true` の `state` で盤面を置き換える(アニメーションはしない)。留守のあいだの出来事は、`events` では届かない(view の内容で分かる)。

**休止(Durable Object の hibernation)**
- 合言葉・猶予の期限・アラームの予約・ゲームの状態・乱数の位置は、すべて Durable Object のストレージにある。休止して起きても、`resume` も猶予切れも、そのまま動く。

**ストレージの書き込み(Q3)**
- 1手(`act` の成功)の書き込みは、**1行**(`state:<部屋ID>`)。断られた手・`resync`・チャット・中継だけのイベント(スタンプ)・`presence` は、書かない。
- 結果が出た手と、開始・終了・切断・resume のときは、部屋の記録も書く。

### 9.6 クライアントの実装と適合テスト
クライアントは、JS(`client-js/netgame/client.js`)と Python(`client/netgame/session.py`、`version=2`)の2つ。どちらも、`snapshot()`(同じ形の状態の一覧)を持ち、`tests/conformance/` のシナリオ(接続 → マッチ → 手 → ルール違反 → スタンプ → チャット → 切断 → resume → 結果 → 自動再接続 → 登録の失敗 → 部屋コード対戦 → 猶予切れ → 戻れない)に対して、同じ `golden.json` と一致する。**この 9 章を変えたら、シナリオと golden も見直す。** 使いかたは `client-js.md`。
