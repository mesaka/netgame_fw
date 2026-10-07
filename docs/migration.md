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

### M1 サーバー
- `lobby_core.js` を、部屋(`players[]`・席・設定)+ イベント登録 + 結果(`ranks`)の形に一般化する。realtime と turns の両方。
- ポコテンのアダプター(`attack` `snap` `over`)を書く。**ポコテンの Node テスト(25件)を移して**、同じ結果になることを確かめる。
- 追加のテスト: 3人の部屋(席・名簿・`ready_state`・一時停止の集合)、turns(手番・`seq`・ハッシュの突き合わせ・`desync`)、イベントの検証と上限。
- Durable Object を、`Lobby` + `Room` に分ける(`worker.js`)。`previews` の設定をテンプレートに入れる。

### M2 クライアントの核
- `netplay.py` / `nettransport.py` / `TextField` / `has_glyph` を、`client/netgame/` に移す。`NetSession` を、席・名簿・`ranks` の形にする。realtime と turns の両方。
- ポコテンの Python テスト(`test_net.py`)のうち、通信・状態に関するものを移す。偽のブラウザ(WebTransport / WebInput)のテストも移す。

### M3 画面部品
- `ui.py` の net 系と、`Net` の共通部分を、`NetGameScene` + `ui/` の部品に移す。`Theme` / `Strings` で差し替え可能にする。
- 画面のスクリーンショットを、各状態(名前・ルーム・テンキー・待機・準備OK・カウントダウン・一時停止・チャット窓・結果・退出)で撮って、ポコテンの現状と見比べる。

### M4 ポコテンを置き換え
- ポコテンが `netgame/`(コピー)を取り込み、`Net` を `PokotenAdapter` + `NetGameScene` に置き換える。重複したコード(`netplay.py` / `nettransport.py` / `ui.py` の net 系 / `server/`)を消す。
- 本番と同じ手順(プレビューのブランチ → 2つのブラウザで確認 → `main`)で、動作が同じであることを確認する。

### M5 ターン制の見本
- ○×(2人)で、手番・ずれの検出・退出・再戦・結果を確かめる。クライアントのテストと、2つの接続を使った通しの確認。
- 3人用の見本(数当てなど)は、「席・名簿・一時停止の集合」の確認用に、サーバー側のテストで先に確かめる(開始方法・退出方針は保留)。

### M6 文書
- 使い方(アダプターの書き方、pygbag と Cloudflare の設定、フォントの作り方、ポコテンへの取り込み手順 `tools/sync_netgame.sh`)を整える。

## 3. 取り込み方(ポコテン側)
- pygbag は、アプリのフォルダ内のファイルだけを梱包する。サブモジュールではなく、**コピー**(`git subtree` または `tools/sync_netgame.sh`)で、`netgame/` に置く。
- サーバーは、`server/` にコピーし、`wrangler.jsonc` は、テンプレートをもとにする(Durable Object のバインディング・マイグレーション・`previews`・`run_worker_first: ["/ws"]`)。

## 4. 完了の条件(M4)
- ポコテンのネット対戦の、仕様(`SPEC.md` 2.8)に書かれたことが、すべて同じに動く。
- ポコテンの Python テスト・Node テストが、通る(移したテストを含む)。
- ポコテンのコードから、通信・流れの共通部分が消えて、アダプターだけが残っている。
