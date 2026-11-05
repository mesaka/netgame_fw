# 設計 v2 — 汎用の対戦ゲームライブラリへ

状態: **設計案(未実装)**。実装前に、ここの「未決事項」を決める。
現在の仕様は `design.md` / `protocol.md` / `adapter.md`(v1)。この文書は、その**追加**を定める。v1 の動作は変えない(ポコテンを壊さない。`migration.md`)。

## 1. 目的

`netgame_fw` を、Pygame / pygbag のゲームだけでなく、**ブラウザ(JS)で作ったゲーム**にも使える、汎用の対戦ゲームライブラリにする。
最初の利用者(検証の相手)は、hiro-hoshi-kazu.com の花札2作品(こいこい・花合わせ。いまは PartyServer / PartySocket で実装)。

ゴール:
1. 花札2作品の対戦(ランダムマッチ・部屋コード・再接続・スタンプ・相手の手札を隠す)を、**いまと同じ体験で**、`netgame_fw` の上で動かす。
2. ポコテン(v1・realtime)と ○×(v1・turns)は、**変えずに動く**。
3. JS クライアントを、Python クライアントと並ぶ**正式なクライアント**にする。

## 2. v1 のままでは足りないこと

| # | 花札に必要 | v1 の状態 | v2 で足すもの |
|---|---|---|---|
| 1 | 相手の手札を送らない(隠し情報) | turns はロックステップ。全員が全手を知る → **守れない** | サーバー権威型の方式 `authoritative` |
| 2 | 切断しても同じ席に戻れる | 切断 = 退出(2人なら相手の勝ち)。`resume` は「将来の拡張」 | 再接続(resume トークン + 猶予時間) |
| 3 | ブラウザ JS のクライアント | クライアントは Python(pygame)のみ。JS はテスト用の薄いもの(`examples/pokoten/e2e.mjs`) | 正式な JS クライアント(画面を含まない通信の部分) |
| 4 | 部屋コード 4文字(英数)+ 招待リンク、**パスワードなし** | ルーム = 6桁の数字 + 4桁のパスワード(必須) | 部屋コードの形式・パスワードの有無を、アダプターで設定 |
| 5 | スタンプ(定型の絵文字を相手に送る) | realtime の `event` だけ。turns では使えない | `event`(中継)を、どの方式でも使える |
| 6 | 対戦中のゲーム内の「次の局へ」(局の終わりの準備OK) | 開始前の `ready` と、結果後の `rematch` だけ | ゲームの中の進行は、ゲーム側(`apply`)が持つ。フレームワークの `ready` は省略できる |
| 7 | 状態の永続化(Durable Object の休止をまたぐ) | 部屋の記録は kv に保存。ゲームの状態は持たない | `authoritative` のゲーム状態を、kv に保存する |

## 3. 新しい方式: `authoritative`(サーバー権威型)

既存の `realtime` / `turns` と並べて、第3の `mode` として足す(`design.md` 3.2、リスクの節の「v2」)。

- **ルールとゲームの状態は、サーバーだけが持つ。** クライアントは「手(action)」を送り、サーバーが検証して適用する。
- サーバーは、各席に**その席から見える範囲(view)だけ**を送る。相手の手札・山札は、サーバーを出ない。
- ゲームのルールは JS(サーバーで動くため)。花札のエンジン(`createGame` / `act` / `viewFor`)は、すでにこの形。

### 3.1 サーバー側のアダプター(JS)

```js
export default {
  id: "awase",
  mode: "authoritative",
  minPlayers: 2, maxPlayers: 2,
  normalizeSettings: (s) => ({ rounds: [3, 6, 12].includes(s?.rounds) ? s.rounds : 3 }),
  matchKey: (settings) => `${settings.rounds}`,

  game: {
    // 新しい対戦の状態を作る。ctx = { settings, players, seed, rng }
    init: (ctx) => createGame({ rounds: ctx.settings.rounds, rng: ctx.rng }),
    // 手を適用する。状態を直接変えてよい(返したあと、フレームワークが保存する)。
    // 戻り値: { ok: true, events?: [...] } | { ok: false, error: "..." }
    apply: (state, seat, action, ctx) => act(state, seat, action, ctx.rng),
    // 席ごとの見える状態。JSON にできる値(相手の手札などを含めない)
    view: (state, seat) => viewFor(state, seat),
    // 対戦の終わりなら { ranks: [{seat, rank}], why? }、続くなら null
    outcome: (state) => (state.phase === "gameEnd" ? ranksOf(state) : null),
  },

  events: { stamp: { to: "others", maxPerSec: 3, validate: (d) => Number.isInteger(d.id) && d.id >= 0 && d.id < 8 } },
  flow: { ready: false, rematch: "game" },          // 4 章
  rooms: { code: "alnum4", password: "none" },      // 6 章
  onLeave: { grace: 60, then: "forfeit" },          // 5 章
};
```

- `state` は **JSON にできる値**にする(関数・`Map`・`Set` を入れない)。フレームワークが、手を適用するたびに kv へ保存する(Durable Object が休止しても失われない)。
- 乱数は `ctx.rng`(`seed` から作る、決定的なもの)を使う。**ゲームの結果を再現・テストできる**。
- `apply` の `events` は、クライアントのアニメーション用(「札を配った」「役ができた」など)。そのまま全員に送る。**events に、隠したい情報を入れない**(席ごとに変えたい場合は `eventsFor(state, seat, events)` を足す: 未決事項 Q4)。

### 3.2 プロトコルの追加(v2)

`/ws?game=<id>&v=2`。`v=1` のクライアントは、これまで通り動く(`authoritative` のゲームには v=2 が必要。`error: version`)。

| 方向 | t | 中身 | 説明 |
|---|---|---|---|
| C→S | `act` | `a`(手)、`n?`(クライアントの通し番号) | 手。サーバーが `apply` する |
| S→C | `state` | `view`, `events`, `seq`, `resync?` | 適用のたびに、各席へ**その席の view** を送る。`resync: true` は、再接続・不一致のときの全体の再送 |
| S→C | `error` | `code: "rule"`, `d: <error>` | `apply` が `ok: false`。直後に、最新の `state`(`resync: true`)を再送する |
| S→C | `presence` | `seat`, `online` | その席がオンライン/切断中 |

- 通し番号 `seq` は、`state` ごとに 1 ずつ増える。クライアントは、飛びを見つけたら `resync` を要求できる(`{t:"resync"}`)。
- v1 の `event`(中継)・`chat`・`leave`・`result` は、そのまま使える。`event` は `authoritative` でも使える(スタンプなど)。
- `result` は、`outcome` が非 null になった時点で、サーバーが送る(`ranks` と `why`)。

## 4. フロー(ready / rematch)を選べるようにする

v1 は「登録 → 部屋が決まる → 全員 `ready` → `start` → 対戦 → `result` → `rematch`」の固定。花札は、**部屋が決まったらすぐ始まり、局ごとの準備OKはゲームの中**にある。

- `flow.ready`: `true`(既定。v1 と同じ)/ `false`(`match` の直後に、サーバーが `start` を送る)。
- `flow.rematch`: `"framework"`(既定。結果のあと、全員が `rematch` を送ると新しい対戦)/ `"game"`(結果のあとの進行は、ゲームの `apply` が持つ。フレームワークは `rematch` を扱わない)。
- `rematch: "game"` のとき、`outcome` が非 null になっても、部屋は `over` にならず、**`playing` のまま**にする。`result` は「結果の通知」だけで、そのあとも `act` を受け付ける(花札は、`gameEnd` のあと、ゲーム内の action `rematch` で次の対戦へ進む)。`outcome` は、**状態が「終わり」へ変わったとき**に1回だけ通知する(`gameEnd` のあいだ、手のたびに送り直さない)。
- ポコテン・○×は、既定のまま(変更なし)。

## 5. 再接続(resume)

### 5.1 トークン
- `registered` に、**席のトークン** `token`(推測できない乱数。サーバーが発行、kv に保存)を足す。クライアントは、これを保存する(ブラウザなら localStorage)。**画面には出さない**。
- 再接続: 新しい WebSocket で `register` の代わりに `{t: "resume", room, token}`。
  - 一致すれば、その席に紐づけ直して、`match`(席・名簿)と、`state`(`resync: true`)を送る。`presence` を全員へ。
  - 一致しなければ `error: "resume"`。クライアントは新規登録からやり直す。
- 発行したトークンは、部屋が消えたら無効になる。

### 5.2 切断の扱い(猶予時間)
- 切断を検出したら、その席を「切断中」にし、全員に `presence {online:false}` を送る。**すぐには退出にしない。**
- Durable Object のアラームで、`onLeave.grace` 秒(既定 60)の猶予を数える。猶予内に `resume` されたら、続ける。過ぎたら `onLeave.then`(`"forfeit"`: 残りの人の勝ち / `"abort"`)を実行する。
- `grace: 0` にすると、v1 と同じ(切断 = すぐ退出)。**v1 のゲームの既定は 0**(動作を変えない)。
- `leave`(自分から出る)は、猶予なしで、すぐ退出。

### 5.3 休止
- いまの `Hub` は、WebSocket Hibernation を使っている。`authoritative` の状態は kv に置くので、休止して起きても続けられる。
- 保存の量: 1手ごとに、状態全体(花札は数KB)を書く。無料枠の範囲に収まるか、実測する(M9 の完了条件)。

## 6. ゲームごとの設定: 部屋コード・パスワード

アダプターの `rooms`:

| 項目 | 値 | 既定(v1) | 花札 |
|---|---|---|---|
| `code` | `"digits6"` / `"alnum4"`(紛らわしい文字を除いた英数 4文字) | `digits6` | `alnum4` |
| `password` | `"required"` / `"optional"` / `"none"` | `required`(4桁の数字) | `none` |
| 招待 | ルームコードだけで入れる(URL にコードを入れて共有) | — | 使う |

- パスワードなしの部屋は、コードの当て推量(総当たり)で入られうる。対策: **1接続あたり、存在しない部屋への参加の失敗を、一定回数まで**(超えたら一定時間、その接続の参加を断る)。`alnum4`(約100万通り)でも、これで現実的な総当たりは防げる。**数値は実装で決める**(未決事項 Q6)。
- 「部屋を作る」と「部屋に入る」は、いまの `register {mode:"friend", room?}` を拡張する(`pass` を、`password: "none"` のときは不要にする)。
- ランダムマッチは、`matchKey` の同じ人どうし(v1 と同じ)。

## 7. JS クライアント(正式)

`client-js/` に置く。**画面を含まない**、通信と状態管理の部分。画面(DOM・canvas)は、ゲームが作る。Python のクライアントの、`session.py`(状態機械)+ `transport.py` に相当する。

```js
import { NetGameClient } from "./netgame/client.js";

const net = new NetGameClient({
  url: "wss://example.com/ws", game: "awase", v: 2,
  storage: localStorage,          // トークンの保存先(省略可。なければメモリ)
  reconnect: { minMs: 1000, maxMs: 10000 },   // 自動再接続(resume つき)
});
net.on("state", ({ view, events, resync }) => { /* 盤面を更新 */ });
net.on("presence", ({ seat, online }) => {});
net.on("result", ({ ranks, why }) => {});
net.on("status", (s) => {});      // "connecting" | "open" | "reconnecting" | "closed"
net.registerRandom({ name, settings });          // ランダムマッチ
net.registerFriend({ name, settings, room });    // room なし = 作る / あり = 入る
net.act({ type: "play", card: 3 });
net.event("stamp", { id: 2 });
net.leave();
```

- 依存なし(ESM)。ブラウザと Node 22 以上(グローバルの `WebSocket`)で動く。
- **自動再接続と `resume` を内蔵**する(花札が PartySocket でやっていること)。送信は、つながるまでバッファする。受信は、`state` を**順番に**1つずつハンドラーに渡す(アニメーション中に次が来ても、順番を守れるよう、ハンドラーが `Promise` を返したら、完了まで次を待つ)。
- v1(realtime / turns)のゲームにも使える(ポコテンの JS 版が欲しくなったときのため)。
- 取り込みは、Python 側と同じく**コピー**(`tools/copy_to_game.sh` に `client-js/` を足す)。npm には公開しない(いまは)。

### 7.1 2つのクライアントを揃える仕組み
- **プロトコルが正**。`protocol.md` に v2 を書き、**適合テスト**を作る: 同じシナリオ(登録 → 対戦 → 切断 → 再接続 → 結果)を、`NetGameCore`(node)に対して、JS クライアントと Python クライアントの両方で実行し、受け取るメッセージの列が同じことを確かめる。
- 画面部品(`ui/`、pygame)は Python だけ。JS には作らない(ゲームごとの DOM になるため)。

## 8. 共通部分とゲーム固有部分

| フレームワーク(共通) | ゲーム(アダプター) |
|---|---|
| 接続・席・名簿・ランダムマッチ・部屋コード・パスワード・招待 | `id`・人数・設定の正規化・`matchKey` |
| 再接続(トークン・猶予・`presence`)・退出・結果の通知 | ルール(`init` / `apply` / `view` / `outcome`) |
| 状態の保存・休止からの復帰・`seq`・`resync` | 中継するイベント(スタンプなど)の定義 |
| レート制限・フレームの大きさの制限・不正な入力の拒否 | 画面・アニメーション・音・CPU 対戦(ブラウザ内) |
| JS / Python のクライアント | |

CPU 対戦(ブラウザ内で完結)は、`netgame_fw` の範囲外。花札の `LocalSession` は、そのまま残す。

## 9. 花札の対応表

| いまの花札(PartyServer) | v2 の `netgame_fw` |
|---|---|
| `HanafudaLobby`(`queue` / `matched`)| ランダムマッチ(`register {mode:"random"}` → `match`)。`matchKey` = モード + ラウンド数 |
| `HanafudaRoom.onConnect`(席の割り当て、`token`)| `register`(friend)/ `resume {room, token}` |
| `?create=1&variant=&rounds=` | `register {mode:"friend", settings}`(`room` なし = 作る) |
| `onMessage {type:"action"}` → `act` → `viewFor` を各席へ | `act` → `apply` → `state {view}` を各席へ |
| `{type:"update", view, events, resync}` | `state {view, events, resync}` |
| `{type:"room", seats[].online}` | `match`(名簿)+ `presence` |
| `{type:"stamp", id}` | `event` `stamp` |
| `{type:"rejected", reason}`(`bad-request` / `not-found` / `full`)| `error`(`room` / `state`)|
| ゲーム内の「次の局へ」(両者の `ready`) | `apply`(ゲームの action) |
| 4文字の部屋コード・招待リンク | `rooms.code: "alnum4"`、`password: "none"` |

## 10. 移行の方法(花札)

1. **並行運転**: 新しいサーバーを、別の経路(例: `/ws?game=awase&v=2`)に置く。いまの `/parties/*`(PartyServer)は、そのまま動かす。
2. クライアント側は、**フラグ**(URL のパラメーターや設定)で、通信の実装を切り替えられるようにする。ゲームの画面は、`session` の同じインターフェース(`onView` / `send` / `stamp`)を使っているので、**通信部分の差し替え**だけで済む(`net.js` の `RemoteSession`)。
3. まず**花合わせ**(役・こいこいがない)で、新旧を比べる。同等になったら、こいこいを移す。
4. 切り替えは、(a) 自動対戦で同じ結果になる (b) 手動の確認(2端末・切断・再接続)が終わる (c) 本番で一部だけ有効にして問題がない、の順。戻せるよう、旧版は、新版が安定するまで残す。

## 11. テスト計画

| 層 | 内容 |
|---|---|
| ルールエンジン | 花札の既存テスト(`scripts/test-*.mjs`)を、そのまま使う |
| サーバーの核 | `NetGameCore` に `authoritative` を足して、`node --test`(席ごとの view に相手の手札が入らない、不正な手の拒否、再接続、猶予切れ、休止からの復帰) |
| プロトコルの適合 | 7.1 の、JS と Python の両クライアント |
| 通し | `wrangler dev` に、JS クライアントで2人分つなぎ、**CPU 同士の自動対戦(数百局)**を、ネット経由で。切断・再接続を、ランダムに挟む |
| 退行 | ポコテンの e2e(`examples/pokoten/`)、○×の e2e。v1 の既存テストが全部通ること |

## 12. 未決事項(実装前に決める)

| # | 問い | 案 |
|---|---|---|
| Q1 | `mode` の名前 | `authoritative` |
| Q2 | `apply` は、状態を直接変える形か、新しい状態を返す形か | 直接変える形(花札の `act` がそう)。保存は、フレームワークが `apply` のあとに行う |
| Q3 | 状態の保存の頻度(1手ごと)の費用 | 実測して決める。重ければ、まとめて保存 |
| Q4 | `events` に隠し情報が入りうるか | 既定は全席に同じ。必要なら `eventsFor(state, seat, events)` を足す |
| Q5 | `flow.rematch: "game"` のとき、`result` のあとの扱い | 4 章の通り(`playing` のまま。`result` は通知だけ。`outcome` は変化したとき1回)。花札の `gameEnd` → `rematch` と対応 |
| Q6 | 当て推量の対策の数値 | 1接続あたり、失敗5回で60秒の拒否(初期値。実装で調整) |
| Q7 | Hub を、部屋ごとの Durable Object に分けるか | v2 の最初は分けない(`design.md` 3.3)。負荷を測ってから |
| Q8 | JS クライアントの配り方 | コピー(Python と同じ)。npm は、必要になったら |
| Q9 | 観戦 | v2 では扱わない |

## 13. マイルストーン

| # | 内容 | 完了条件 |
|---|---|---|
| M7 | この設計の確定 + `protocol.md` に v2 を追記 | 未決事項が決まり、レビューが済む |
| M8 | サーバーの核: `authoritative`・`flow`・`rooms`・`state`/`act`・テスト | `npm test` が通る。ポコテン・○×の既存テストが無変更で通る |
| M9 | 再接続(トークン・猶予・`presence`・休止からの復帰) | 切断・再接続・猶予切れ・休止のテスト。状態の保存の量を実測 |
| M10 | JS クライアント + 適合テスト | JS と Python のクライアントで、同じシナリオが通る |
| M11 | 花合わせを `netgame_fw` で動かす(`hiro-hoshi-kazu-web`、並行運転) | 自動対戦(ネット経由)が通り、2端末で手動確認 |
| M12 | こいこいを移す → 旧版を外す → 記事の書き直しと公開 | 本番で問題なし。ブログの保留記事を、制作記事と合わせて公開 |
