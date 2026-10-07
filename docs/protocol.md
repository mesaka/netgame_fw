# 通信プロトコル v1

WebSocket のテキストフレーム。1フレーム = 1つの JSON オブジェクト(`t` が種類)。
クライアント → サーバーは、ASCII だけの JSON(`\uXXXX` のエスケープ)で送る。サーバー → クライアントも、ブラウザ側の橋渡しが ASCII に直して渡す。
生存確認: クライアントが文字列 `ping` を送ると、サーバー(Durable Object を起こさずに)`pong` を返す。20秒おきに送る。

接続先: `/ws?game=<ゲームID>&v=1`。ゲームIDが未登録・版が合わない場合は、`error`(`code: "game"` / `"version"`)を送って閉じる。

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
`name`(名前が空) / `key`(パスワードが4桁の数字でない) / `room`(ルームがない・満員・対戦中・間違いが続いて閉じた) / `pass`(パスワードが違う) / `game`(未登録のゲーム) / `version`(版が違う) / `rate`(送りすぎ) / `state`(いまの状態では送れない)。
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
