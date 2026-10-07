# 移行の手順(ポコテンから netgame_fw へ)

ポコテン(mesaka/pokoten)の動作は、**M4 までは変えない**。各段階で、ポコテンの既存テスト(Python / Node)を通し続ける。

## 1. 現在のポコテンの通信と、プロトコル v1 との対応

| 現在(pokoten) | v1 | 備考 |
|---|---|---|
| `hello {id}` | `hello {id, v, game, config}` | `config` を足す |
| `register {name, diff, mode, pass?, room?}` | `register {name, mode, settings:{diff}, pass?, room?}` | `diff` → `settings.diff` |
| `waiting {room?}` | 同じ | |
| `match {seed, diff, you, opp:{id,name}}` | `match {seed, you, players:[{seat,name}], settings, mode}` | `opp` → `players` |
| `ready`(クライアント) | 同じ | |
| `opp_ready` | `ready_state {seats}` | 席の一覧にする |
| `start` | `start {turn?}` | |
| `pause {on}` / `paused {on}` | `pause {on}` / `paused {seat, on}` | 席を足す |
| `attack {n}` → `garbage {n}` | `event {k:"attack", d:{n}}` → `event {seat, k, d}` | アダプターのイベント |
| `snap {b, sc, g}` → `snap` | `event {k:"snap", d:{b, sc, g}}` | 同上 |
| `over` → `result {r:"win"/"lose"}` | `event {k:"over"}` → `result {ranks, why}` | `r` → `ranks`(席ごとの順位) |
| `result {r:"win", why:"left"}` | `result {ranks, why:"left"}` | |
| `chat {text}` → `chat {from, name, text}` | `chat {text}` → `chat {seat, name, text}` | `from`(接続ID)→ `seat` |
| `rematch` / `rematch_req` | `rematch` / `rematch_req {seat}` | |
| `opp_left` | `player_left {seat}` | |
| `error {code}` | 同じ(コードを足す) | |

## 2. 段階

### M0 設計と仕様(いまここ)
- 新リポジトリに、README・設計・プロトコル・アダプターの仕様・移行手順を置く。

### M1 サーバー(実装済み。PR で確認中)
- 実装: `server/core.js`(核)・`server/worker.js`(Cloudflare の入口)・`server/text.js`・`server/testkit.js`(テスト用の部品)。
- ポコテンのアダプター(見本): `examples/pokoten/adapter.js`。`attack` `snap` `over` を、イベントとして登録している。
- テスト: `server/core.test.js`(共通。realtime・turns・ルーム・3人の部屋)37件 + `examples/pokoten/adapter.test.js`(ポコテン固有)12件。ポコテンの既存の Node テスト(25件)の内容は、共通のものを `core.test.js` に、ポコテン固有のものを `adapter.test.js` に、v1 の通信で移した。
- 本物の Workers ランタイムでの確認: `examples/pokoten/e2e.mjs`(ランダム・ルーム・準備OK・一時停止・チャット・再戦・退出)。
- **当初の予定からの変更**: Durable Object は、まだ `Lobby` + `Room` に分けず、**1つの `Hub`** で、組み合わせも部屋も動かす。部屋の記録は DO のストレージ(`ctx.storage.kv`。同期 KV)に置く。部屋ごとに分けるのは、規模が必要になってから(`docs/design.md` 3.3)。
- 元の計画(参考):
- `lobby_core.js` を、部屋(`players[]`・席・設定)+ イベント登録 + 結果(`ranks`)の形に一般化する。realtime と turns の両方。
- ポコテンのアダプター(`attack` `snap` `over`)を書く。**ポコテンの Node テスト(25件)を移して**、同じ結果になることを確かめる。
- 追加のテスト: 3人の部屋(席・名簿・`ready_state`・一時停止の集合)、turns(手番・`seq`・ハッシュの突き合わせ・`desync`)、イベントの検証と上限。
- Durable Object を、`Lobby` + `Room` に分ける(`worker.js`)。`previews` の設定をテンプレートに入れる。

### M2 クライアントの核(実装済み。PR で確認中)
- 実装: `client/netgame/` — `protocol.py`(定数・順位の検査)/ `text.py`(`clean_text`・`TextField`・`has_glyph`・`printable`)/ `webbridge.py`(JS の SHIM・`WebInput`・コピー・貼り付け・保存)/ `transport.py`(`WebTransport`・`ThreadTransport`)/ `session.py`(`NetSession`)。
- `NetSession` は、v1 の通信・席・名簿・順位の形。realtime(`send_event` / `take_events`)と turns(`send_action` / `take_actions` / `send_sync` / `report_finish`)の両方。2人対戦向けの窓口(`opp_name` `opp_ready` `opp_left` `result` など)も用意した。
- テスト(pytest 35件): `tests/test_session.py`(ポコテンの `test_net.py` の通信・状態のテストを、v1 の形で移した + turns・3人)/ `test_text.py` / `test_webbridge.py`(偽のブラウザ・SHIM を node で動かす `shim_test.cjs`)。
- 本物の Workers ランタイムでの確認: `examples/pokoten/e2e_client.py`(Python のクライアント + 実際の WebSocket。ランダム・ルーム・準備OK・一時停止・チャット・再戦・退出)。
- 移行で変えたところ: JS 側の名前を `pkNet` → `ngNet`、`N.open(url, query)` が `?game=…&v=1` を受け取る、PC の接続先の環境変数を `POKOTEN_SERVER` → `NETGAME_SERVER`、`web_prompt`(使っていなかった入力ダイアログ)は持ち込まない。
- 元の計画(参考):
- `netplay.py` / `nettransport.py` / `TextField` / `has_glyph` を、`client/netgame/` に移す。`NetSession` を、席・名簿・`ranks` の形にする。realtime と turns の両方。
- ポコテンの Python テスト(`test_net.py`)のうち、通信・状態に関するものを移す。偽のブラウザ(WebTransport / WebInput)のテストも移す。

### M3 画面部品(実装済み。PR で確認中)
- 実装: `client/netgame/flow.py`(`NetGameScene`: 接続 → 名前 → 相手さがし/ルーム(テンキー) → 準備OK → カウントダウン → 対戦 → 結果 → 再戦/退出、チャットと一時停止、ブラウザの入力欄との同期)/ `adapter.py`(ゲーム側が書く `GameAdapter` / `RealtimeAdapter`)/ `ui/`(`theme.py` 色・フォント・背景 / `strings.py` + `strings_ja.py` 文言 / `layout.py` 置き場所 / `widgets.py` ボタン・入力欄・確認・`ClickPad` / `screens.py` 各画面と窓 / `chat.py` 定型文の選び方)。使い方は `docs/ui.md`。
- ポコテンの `Net`(約 600 行)の流れを、ゲームに依存しない形で移した。盤面を動かす・描く部分だけが、アダプターの `start_match` / `update` / `draw` / `handle` に残る。
- テスト(pytest 78件のうち 43件): `tests/test_flow.py` — 偽の通信 + 画面なしの pygame で、名前・ルーム(テンキー・キーボード・貼り付け)・準備OK・カウントダウン・チャットの一時停止と再開・確認・決着・再戦・退出・自動退出・ブラウザの入力欄の同期、全画面の描画(480×800 / 960×720 / 1024×900)。
- ポコテンとの見比べ: `tools/compare_pokoten.py --pokoten <ポコテンの場所>` が、同じデータで描いた**55 の画面・部品が、ピクセル単位で一致する**ことを確かめる(名前・テンキー3種・待機・エラー・チャットの窓4種・右の列のボタン・準備OK・確認。押している状態も)。盤面・得点・相手の小さな盤面・音量ボタンは、ゲーム側(アダプター)の受け持ち。
- 変えたところ: 画面の置き場所は、基準 480×800 の座標を中央に置く(`Layout`)。大きい画面でも崩れないが、横長の専用レイアウトはまだない。エラーの文字色を `Theme.error` に分けた。文言の `net_diff`(むずかしさ)は持たず、アダプターの `settings_label()` が返す。
- 元の計画(参考): `ui.py` の net 系と、`Net` の共通部分を、`NetGameScene` + `ui/` の部品に移す。`Theme` / `Strings` で差し替え可能にする。各状態のスクリーンショットを、ポコテンの現状と見比べる。

### M4 ポコテンを置き換え
- ポコテンが `netgame/`(コピー)を取り込み、`Net` を `PokotenAdapter` + `NetGameScene` に置き換える。重複したコード(`netplay.py` / `nettransport.py` / `ui.py` の net 系 / `server/`)を消す。
- 本番と同じ手順(プレビューのブランチ → 2つのブラウザで確認 → `main`)で、動作が同じであることを確認する。

### M5 ターン制の見本(実装済み。PR で確認中)
- クライアント: `TurnAdapter`(`client/netgame/adapter.py`)— 届いた手の適用・ハッシュ(`sync`)の送信・終局の申告(`finish`)・同じ手の二重適用の防止。`GameAdapter.sess`(通信)を `NetGameScene` が入れる。結果が `desync` / `abort` のときの説明の文言(`net_desync` / `net_abort`)を足した。
- ○×(2人)の見本: `examples/tictactoe/` — サーバー側 `adapter.js` / ルール `ttt_rules.py`(pygame 非依存。不正な手は全員が同じく無視)/ クライアント `ttt_client.py`(盤面をクリックして指す)/ ローカル用の `worker.js` `wrangler.jsonc` / 実サーバーでの通し確認 `e2e.py`。
- 3人用の見本: `examples/guess3/`(数当て。サーバー側のみ)— 席・名簿・準備OK・手番の巡り・ハッシュの突き合わせ・結果の一致・退出・一時停止の集合を、3人の部屋で確かめた。
- テスト: node 62件(うち ○× 5件・数当て 8件)/ pytest 91件(うち `tests/test_tictactoe.py` 13件: ルール・クリック→手の送信・ハッシュの一致・二重適用・勝ちの申告・チャット中の手の待機・desync の表示・描画)。
- 実サーバー(`wrangler dev`)での確認: `e2e.py` で2つの `NetGameScene` を本物の WebSocket でつなぎ、先手の決定・手番でないクリックの無視・5手での決着(勝ち/負け)・再戦で盤面が空に戻る・途中退出で残った側の勝ち、を通した。
- 変えなかったこと / 保留のまま: 3人以上の開始方法・途中退出の扱い(いまは中止 `abort`)、横長の専用レイアウト、○×の先手の入れ替え(再戦でも席0から)。
- ブラウザ(pygbag)での ○× の実機確認は、していない(ポコテンのような取り込み先がまだない)。
- 元の計画(参考): ○×(2人)で、手番・ずれの検出・退出・再戦・結果を確かめる。3人用の見本(数当てなど)は、サーバー側のテストで先に確かめる。

### M6 文書
- 使い方(アダプターの書き方、pygbag と Cloudflare の設定、フォントの作り方、ポコテンへの取り込み手順 `tools/sync_netgame.sh`)を整える。

## 3. 取り込み方(ポコテン側)
- pygbag は、アプリのフォルダ内のファイルだけを梱包する。サブモジュールではなく、**コピー**(`git subtree` または `tools/sync_netgame.sh`)で、`netgame/` に置く。
- サーバーは、`server/` にコピーし、`wrangler.jsonc` は、テンプレートをもとにする(Durable Object のバインディング・マイグレーション・`previews`・`run_worker_first: ["/ws"]`)。

## 4. 完了の条件(M4)
- ポコテンのネット対戦の、仕様(`SPEC.md` 2.8)に書かれたことが、すべて同じに動く。
- ポコテンの Python テスト・Node テストが、通る(移したテストを含む)。
- ポコテンのコードから、通信・流れの共通部分が消えて、アダプターだけが残っている。
