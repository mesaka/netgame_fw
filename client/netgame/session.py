"""サーバーとの1回の接続(pygame非依存)。画面(flow)は、これを見て描くだけ。通信の仕様は docs/protocol.md。

state:
  connecting → idle(接続した。名前待ち) → waiting(登録した。相手待ち) → ready(部屋が決まった。準備OK待ち)
  → playing(対戦中) → over(決着。チャットは続けられる) / closed(切断・失敗: error に理由)

realtime と turns の両方を扱う。v=2(NetSession(version=2))では、サーバー権威型(authoritative: act / state)・再接続(resume / presence)も扱う
(画面部品 flow.py は v1 だけを使う。v=2 の使いかたは docs/client-js.md と同じ形の API)。席(seat)・名簿(players)・順位(ranks)の形なので、3人以上でもそのまま使える
(3人以上の開始方法・途中退出の続行は、将来の拡張)。2人対戦向けに、opp_* の便利な窓口も用意してある。
"""
from __future__ import annotations

import json
import time

from .protocol import (CONNECT_TIMEOUT, FREE_TIME, IDLE_GRACE, LEAVE_TIMEOUT, MAX_CHAT, MAX_NAME, MAX_PROTOCOL_VERSION,
                       PAUSE_MAX, PING_INTERVAL, PASS_LEN, PROTOCOL_VERSION, RETRY_ERRORS, ROOM_LEN, clean_digits,
                       clean_room_code, rank_of, valid_ranks)
from .text import clean_text
from .transport import Transport


class NetSession:
    def __init__(self, transport: Transport, game: str, clock=time.monotonic, default_name="相手", version=PROTOCOL_VERSION):
        if version not in range(PROTOCOL_VERSION, MAX_PROTOCOL_VERSION + 1):
            raise ValueError("version は 1 か 2")
        self.t = transport
        self.version = version                # 1(既定。realtime / turns)か 2(authoritative・再接続も)
        self.game = game
        self.clock = clock
        self.default_name = default_name      # 名前が空の人の表示名
        self.state = "connecting"
        self.error = None                     # "connect"(つながらない) / "lost"(途切れた) / "timeout"(決着後、操作がなかった)
                                              # / "game" / "version" / サーバーのエラーコード
        self.notice = None                    # 登録をやり直す理由("name" / "key" / "room" / "pass")
        self.conn_id = None                   # サーバーが発行した接続ID(画面には出さない)
        self.config = {}                      # hello の config: min_players / max_players / mode / limits
        self.limits = {}
        # 登録
        self.name = ""
        self.mode = "random"                  # "random" / "friend"
        self.settings = {}
        self.room_id = ""                     # ルームID(ルームを作った人には、サーバーが発行する)
        self.password = ""
        # 部屋
        self.match_no = 0                     # match が届くたびに増える(画面が新しい対戦の開始に気づくため)
        self.seat = 0                         # 自分の席
        self.players = []                     # [{"seat", "name"}]
        self.seed = None
        self.game_mode = "realtime"           # "realtime" / "turns"
        self.ready_seats = set()
        self.ready_sent = False               # 自分が準備OKを押した(一度押したら、新しい対戦まで変えない)
        self.start_no = 0                     # start が届くたびに増える(画面がカウントダウンを始める合図)
        self.paused_seats = set()             # 止めている席
        self._paused_at = {}
        self._pause_since = 0.0
        # 対戦
        self.events = []                      # [(seat, kind, data)] realtime: 他の席から届いたイベント
        self.actions = []                     # [(seat, seq, data)] turns: 届いた手(自分の手も。この順に適用する)
        self.turn = None                      # turns: {"seat", "seq"}(いまの手番)
        self.desync_seq = None
        # 結果
        self.ranks = None                     # [{"seat", "rank"}]
        self.why = None                       # "normal" / "left" / "desync" / "abort"
        self.over_since = None
        self.last_op = None                   # 決着後、最後に操作(チャット・再戦)があった時刻
        self.left_seats = set()
        self.left_at = None                   # 相手の退出に気づいた時刻
        self.rematch_seats = set()
        self.rematch_sent = False
        # チャット
        self.chat = []                        # [(自分か, 名前, 本文)]
        self.chat_seen = 0                    # 画面が読んだ数
        self.sent_end_chat = False            # 決着後に、すでに1つチャットを送ったか
        # v=2
        self.token = ""                       # 再接続用の席の合言葉(authoritative)。画面には出さない
        self.room_code = ""                   # 部屋コード(waiting / match / resumed で届く)
        self.view = None                      # authoritative: いまの自分の view
        self.view_seq = None
        self.view_events = []                 # 直近の state の events
        self.view_resync = False
        self.views = []                       # [(seq, view, events, resync)] 届いた state(取り出すまでためる)
        self.event_log = []                   # 中継された event([seat, k, d])の履歴(新しい対戦まで)
        self.offline_seats = set()            # 切断中の席(presence)
        self.errors = []                      # サーバーから届いたエラーコード(順に)
        self.rule_errors = []                 # act が断られた理由(error: rule の d)
        self.result_no = 0                    # result が届くたびに増える
        self.closing = False
        self._started = clock()
        self._last_send = clock()

    # ---- 窓口(便利な読み出し) ----
    @property
    def you(self):
        return self.seat

    @property
    def others(self):
        return [p for p in self.players if p["seat"] != self.seat]

    @property
    def opp_name(self):
        """2人対戦の相手の名前(いなければ None)。"""
        o = self.others
        return o[0]["name"] if o else None

    @property
    def opp_ready(self):
        return any(s != self.seat for s in self.ready_seats)

    @property
    def opp_left(self):
        """相手が退出した(2人対戦。3人以上では、誰か1人でも抜けたら True)。"""
        return bool(self.left_seats - {self.seat})

    @property
    def opp_wants_rematch(self):
        return bool(self.rematch_seats - {self.seat})

    @property
    def paused_me(self):
        return self.seat in self.paused_seats

    @property
    def paused_opp(self):
        return bool(self.paused_seats - {self.seat})

    @property
    def frozen(self):
        """どちらかがチャット中で、ゲームを止める間。"""
        return bool(self.paused_seats)

    @property
    def pause_age(self) -> float:
        """自分が止めてから経った秒数(止めていなければ 0)。"""
        return self.clock() - self._pause_since if self.paused_me else 0.0

    @property
    def my_rank(self):
        return rank_of(self.ranks, self.seat)

    @property
    def result(self):
        """自分から見た結果: "win"(1位) / "lose" / "draw"(全員が1位) / None(まだ)。2人対戦向け。"""
        if self.ranks is None:
            return None
        if all(r["rank"] == 1 for r in self.ranks):
            return "draw"
        return "win" if self.my_rank == 1 else "lose"

    @property
    def my_turn(self):
        return self.state == "playing" and bool(self.turn) and self.turn["seat"] == self.seat

    @property
    def unread_chat(self) -> int:
        return len(self.chat) - self.chat_seen

    # ---- 送信 ----
    def _send(self, obj):
        if self.t.state == "closed":
            return
        self.t.send(json.dumps(obj, ensure_ascii=True, separators=(",", ":")))
        self._last_send = self.clock()

    def start(self, url=""):
        if self.version == PROTOCOL_VERSION:
            self.t.open(self.game, url)              # v1: これまでと同じ呼びかた
        else:
            self.t.open(self.game, url, self.version)

    def register(self, name, mode="random", settings=None, password=None, room=None):
        """名前を登録して、対戦相手をさがす。
        mode: "random" = 同じ条件(settings から、ゲームが決める)で待っている人と、自動で組む。
              "friend" = ルーム方式。room なし = ルームを作って待つ(サーバーがルームIDを発行する。password = 入室に必要な4桁)。
              room あり = そのルームID・パスワードでルームに入る(設定は、作った人のもの)。"""
        name = clean_text(name, self.limits.get("name", MAX_NAME))
        if self.state != "idle" or not name:
            return False
        msg = {"t": "register", "name": name, "mode": mode}
        if settings:
            msg["settings"] = settings
        if mode == "friend" and self.version >= 2:
            rooms = self.config.get("rooms") or {}                # ゲームごとの設定: 部屋コードの形式・パスワードの要否
            kind, pw = rooms.get("code", "digits6"), rooms.get("password", "required")
            given = password is not None and str(password) != ""
            p = clean_digits(password, PASS_LEN) if given else ""
            if pw == "required" and not p or pw == "optional" and given and not p:
                self.notice = "key"
                return False
            r = clean_room_code(room, kind) if room is not None else None
            if room is not None and not r:
                self.notice = "room"
                return False
            if pw != "none" and p:
                msg["pass"] = p
            if r:
                msg["room"] = r
            self.password, self.room_id = (p if pw != "none" else ""), r or ""
        elif mode == "friend":
            p = clean_digits(password, PASS_LEN)
            r = clean_digits(room, ROOM_LEN) if room is not None else None
            if not p:
                self.notice = "key"
                return False
            if room is not None and not r:
                self.notice = "room"
                return False
            msg["pass"] = p
            if r:
                msg["room"] = r
            self.password, self.room_id = p, r or ""
        self.name, self.mode, self.settings = name, mode, settings or {}
        self.notice = None
        self._send(msg)
        self.state = "waiting"
        return True

    def ready(self):
        """準備OK。全員が押すと start が届く。一度押したら、取り消せない・変わらない。"""
        if self.state == "ready" and not self.ready_sent:
            self.ready_sent = True
            self._send({"t": "ready"})

    def set_pause(self, on: bool):
        """チャットの入力・選択を始める/終える。対戦中なら、他の席のゲームも止まる/再開する。"""
        if self.state != "playing":
            on = False
        if on != self.paused_me:
            if on:
                self.paused_seats.add(self.seat)
                self._pause_since = self.clock()
            else:
                self.paused_seats.discard(self.seat)
            if self.state == "playing":
                self._send({"t": "pause", "on": on})

    def send_event(self, kind, data=None):
        """realtime: ゲームのイベントを、他の席へ送る(登録のある kind だけ、サーバーが中継する)。"""
        if self.state == "playing" and (self.game_mode == "realtime" or self.version >= 2):   # v=2: スタンプなどは、どの方式でも
            self._send({"t": "event", "k": kind, "d": data if data is not None else {}})

    def act(self, action=None):
        """v=2 authoritative: 手を送る。結果は、サーバーから届く state(take_views)で受け取る。自分の盤面は、それまで変えない。"""
        if self.version < 2 or self.state != "playing":
            return False
        self._send({"t": "act", "a": action if action is not None else {}})
        return True

    def resync(self):
        """v=2: 自分の最新の view を、もう一度送ってもらう。"""
        if self.version < 2 or self.state != "playing":
            return False
        self._send({"t": "resync"})
        return True

    def resume(self, room=None, token=None):
        """v=2: 切れた席に、この接続で戻る(hello のあと = state が idle のとき)。room / token を省くと、いまの値を使う。
        戻れたら resumed のあと、いまの状態(state など)が届く。戻れなければ state は idle に戻り、notice が "resume" になる。"""
        room, token = room or self.room_code, token or self.token
        if self.version < 2 or self.state != "idle" or not room or not token:
            return False
        self._send({"t": "resume", "room": str(room), "token": str(token)})
        self.state = "resuming"
        return True

    def send_action(self, data=None):
        """turns: 手を送る。手番でなければ送らない(False)。自分の盤面は、サーバーから届いた action で変える。"""
        if not self.my_turn or self.game_mode != "turns":
            return False
        self._send({"t": "action", "seq": self.turn["seq"], "d": data if data is not None else {}})
        return True

    def send_sync(self, seq, digest):
        """turns: 手 seq を適用したあとの状態のハッシュ(文字列・64文字まで)。全員の分が、サーバーで突き合わされる。"""
        if self.state == "playing" and self.game_mode == "turns":
            self._send({"t": "sync", "seq": int(seq), "h": str(digest)[:64]})

    def report_finish(self, ranks):
        """ゲームが終わったと申告する(ranks = [{seat, rank}])。確定は、サーバーのアダプターの規則に従う。"""
        if self.state == "playing" and valid_ranks(ranks, len(self.players)):
            self._send({"t": "finish", "ranks": ranks})
            return True
        return False

    def say(self, text):
        text = clean_text(text, self.limits.get("chat", MAX_CHAT))
        if text and self.state in ("ready", "playing", "over") and not (self.state == "over" and self.opp_left):
            self._send({"t": "chat", "text": text})
            if self.state == "over":
                self.sent_end_chat = True
                self.touch()
            return True
        return False

    def rematch(self):
        if self.state == "over" and not self.opp_left and not self.rematch_sent:
            self.rematch_sent = True
            self.rematch_seats.add(self.seat)
            self.touch()
            self._send({"t": "rematch"})

    def close(self):
        self.closing = True
        self.t.close()
        self.state = "closed"

    def take_events(self):
        out, self.events = self.events, []
        return out

    def take_views(self):
        """v=2 authoritative: 届いた state を、古い順に全部返す: [(seq, view, events, resync)]。"""
        out, self.views = self.views, []
        return out

    def take_actions(self):
        out, self.actions = self.actions, []
        return out

    # ---- 時間 ----
    def touch(self):
        """決着後の操作があった(チャット・再戦)。退出までの時間が延びる。"""
        self.last_op = self.clock()

    def idle_left(self):
        """決着後、自動で退出するまでの残り秒数。まだ余裕がある(IDLE_GRACE より多い)・対象外なら None。
        決着から FREE_TIME は自由時間。それが過ぎたあと、IDLE_GRACE 秒の間に何も操作(チャット・再戦)がなければ退出する。"""
        if self.state != "over" or self.opp_left or self.over_since is None:
            return None
        deadline = max(self.over_since + FREE_TIME, self.last_op or self.over_since) + IDLE_GRACE
        left = deadline - self.clock()
        return left if left <= IDLE_GRACE else None

    def leave_left(self):
        """相手が退出したあと、自動でタイトルに戻るまでの残り秒数。退出していなければ None。"""
        if not self.opp_left or self.left_at is None:
            return None
        return LEAVE_TIMEOUT - (self.clock() - self.left_at)

    def _mark_left(self, seats):
        new = set(seats) - self.left_seats
        self.left_seats |= set(seats)
        if new and self.left_at is None:
            self.left_at = self.clock()

    # ---- 受信・時間の経過 ----
    def update(self):
        for raw in self.t.poll():
            self._handle(raw)
        if self.state == "closed" or self.closing:
            return
        now = self.clock()
        for seat, at in list(self._paused_at.items()):       # 相手の「再開」が届かなくても、止めっぱなしにしない
            if seat in self.paused_seats and now - at > PAUSE_MAX + 10:
                self.paused_seats.discard(seat)
        left = self.idle_left()
        if left is not None and left <= 0:
            self.close()                                      # 決着後、しばらく何も操作がなかったので、ルームから退出する
            self.error = "timeout"
            return
        if self.t.state == "closed":
            self.state = "closed"
            self.error = "lost" if self.t.opened else "connect"
        elif self.state == "connecting" and now - self._started > CONNECT_TIMEOUT:
            self.t.close()
            self.state, self.error = "closed", "connect"
        elif self.t.state == "open" and now - self._last_send > PING_INTERVAL:
            self.t.send("ping")
            self._last_send = now

    def _handle(self, raw):
        try:
            m = json.loads(raw)
        except (TypeError, ValueError):
            return                                            # "pong" など
        if not isinstance(m, dict):
            return
        k = m.get("t")
        h = getattr(self, "_on_" + str(k), None)
        if h and str(k).isidentifier() and not str(k).startswith("_"):
            h(m)

    def _on_hello(self, m):
        if self.state != "connecting":
            return
        if m.get("v", PROTOCOL_VERSION) != self.version:
            self.error, self.state = "version", "closed"
            return
        self.conn_id = str(m.get("id", ""))
        self.config = m.get("config") or {}
        self.limits = self.config.get("limits") or {}
        self.state = "idle"

    def _on_registered(self, m):
        if m.get("token"):
            self.token = str(m["token"])

    def _on_waiting(self, m):
        if m.get("room") and self.mode == "friend":
            self.room_id = str(m["room"])
        if m.get("room"):
            self.room_code = str(m["room"])

    def _on_match(self, m):
        seed = int(m.get("seed", 0))
        players = [{"seat": int(p.get("seat", i)), "name": clean_text(p.get("name", ""), self.limits.get("name", MAX_NAME))
                    or self.default_name} for i, p in enumerate(m.get("players") or [])]
        you = int(m.get("you", 0))
        if self.state in ("ready", "playing") and seed == self.seed and players == self.players and you == self.seat:
            return                                            # 同じ組み合わせの match がもう一度届いても、準備OKなどの状態は変えない
        self.seat, self.players, self.seed = you, players, seed
        if m.get("room"):
            self.room_code = str(m["room"])
        self.view, self.view_seq, self.view_events, self.view_resync = None, None, [], False
        self.views, self.event_log, self.offline_seats = [], [], set()
        self.settings = m.get("settings") or self.settings
        self.game_mode = m.get("mode", "realtime")
        self.state = "ready"
        self.match_no += 1
        self.ready_seats, self.ready_sent = set(), False
        self.paused_seats, self._paused_at = set(), {}
        self.events, self.actions, self.turn, self.desync_seq = [], [], None, None
        self.ranks = self.why = None
        self.over_since = self.last_op = None
        self.left_seats, self.left_at = set(), None
        self.rematch_seats, self.rematch_sent, self.sent_end_chat = set(), False, False

    def _on_ready_state(self, m):
        if self.state == "ready":
            self.ready_seats = {int(s) for s in m.get("seats", [])}

    def _on_start(self, m):
        if self.state != "ready":
            return
        self.state = "playing"
        self.start_no += 1
        t = m.get("turn")
        self.turn = {"seat": int(t["seat"]), "seq": int(t["seq"])} if isinstance(t, dict) else None

    def _on_paused(self, m):
        if self.state != "playing":
            return
        seat = int(m.get("seat", -1))
        if m.get("on") is True:
            self.paused_seats.add(seat)
            self._paused_at[seat] = self.clock()
        else:
            self.paused_seats.discard(seat)

    def _on_event(self, m):
        if self.state == "playing":
            d = m.get("d") if m.get("d") is not None else {}
            self.events.append((int(m.get("seat", -1)), str(m.get("k", "")), d))
            self.event_log.append([int(m.get("seat", -1)), str(m.get("k", "")), d])

    def _on_state(self, m):
        if self.state != "playing":
            return
        self.view, self.view_seq = m.get("view"), m.get("seq")
        self.view_events, self.view_resync = m.get("events") or [], bool(m.get("resync"))
        self.views.append((self.view_seq, self.view, self.view_events, self.view_resync))

    def _on_presence(self, m):
        seat = int(m.get("seat", -1))
        if m.get("online"):
            self.offline_seats.discard(seat)
        else:
            self.offline_seats.add(seat)

    def _on_resumed(self, m):
        """再接続できた。席・名簿・部屋の状態を取り戻す(このあと、状態に応じて state / ready_state / result が届く)。"""
        if self.state != "resuming":
            return
        lim = self.limits.get("name", MAX_NAME)
        self.seat, self.seed = int(m.get("you", 0)), m.get("seed")
        self.room_code = str(m.get("room", ""))
        self.players = [{"seat": int(p.get("seat", i)), "name": clean_text(p.get("name", ""), lim) or self.default_name}
                        for i, p in enumerate(m.get("players") or [])]
        self.settings, self.game_mode = m.get("settings") or {}, m.get("mode", "realtime")
        self.view, self.view_seq, self.view_events, self.view_resync = None, None, [], False
        self.views, self.event_log, self.offline_seats = [], [], set()
        self.ready_seats, self.paused_seats, self._paused_at = set(), set(), {}
        self.left_seats, self.left_at, self.rematch_seats = set(), None, set()
        self.state = {"waiting": "waiting", "ready": "ready", "playing": "playing", "over": "over"}.get(m.get("status"), "playing")
        self.notice = None

    def _on_action(self, m):
        if self.state == "playing":
            self.actions.append((int(m.get("seat", -1)), int(m.get("seq", -1)), m.get("d") if m.get("d") is not None else {}))

    def _on_turn(self, m):
        if self.state == "playing":
            self.turn = {"seat": int(m.get("seat", 0)), "seq": int(m.get("seq", 0))}

    def _on_desync(self, m):
        self.desync_seq = int(m.get("seq", 0))

    def _on_result(self, m):
        resumed_over = self.state == "over" and self.ranks is None         # 再接続で、終わった部屋に戻った
        if self.state not in ("ready", "playing") and not resumed_over:
            return
        self.result_no += 1
        self.ranks = m.get("ranks") or []
        self.why = m.get("why", "normal")
        flow = self.config.get("flow") or {}
        if self.game_mode == "authoritative" and flow.get("rematch") == "game" and self.why == "normal":
            return                                              # 部屋は playing のまま。結果は通知だけで、そのあとも act できる
        self.state = "over"
        self.paused_seats, self._paused_at = set(), {}
        self.over_since = self.last_op = self.clock()
        if self.why == "left":                                 # 2人対戦では、残りが勝つ。抜けたのは、自分以外
            self._mark_left([p["seat"] for p in self.players if p["seat"] != self.seat])

    def _on_chat(self, m):
        text = clean_text(m.get("text", ""), self.limits.get("chat", MAX_CHAT))
        if not text:
            return
        seat = m.get("seat")
        self.chat.append((seat == self.seat, clean_text(m.get("name", ""), self.limits.get("name", MAX_NAME)), text))
        del self.chat[:-30]
        if self.state == "over":
            self.touch()                                       # 相手とやりとりしている間は、部屋を閉じない

    def _on_rematch_req(self, m):
        self.rematch_seats.add(int(m.get("seat", -1)))
        if self.state == "over":
            self.touch()

    def _on_player_left(self, m):
        self._mark_left([int(m.get("seat", -1))])

    def _on_error(self, m):
        code = str(m.get("code", "server"))
        self.errors.append(code)
        if code == "rule":
            self.rule_errors.append(m.get("d"))
        if code == "resume":                                     # 戻れない(部屋がない・合言葉が違う・猶予切れ)
            self.token, self.room_code = "", ""
            if self.state == "resuming":
                self.state, self.notice = "idle", "resume"
            return
        if self.state == "waiting" and code in RETRY_ERRORS:
            self.state, self.notice = "idle", code             # 登録は受け付けられなかった。やり直せる
        elif code in ("game", "version"):
            self.error, self.state = code, "closed"
        elif self.state == "connecting":
            self.error = code

    # ---- 状態の一覧(適合テストと、デバッグ用) ----
    def snapshot(self) -> dict:
        """JS 版 NetGameClient.snapshot() と同じ形の、いまの状態。2つのクライアントが同じ解釈をすることの確認に使う
        (tests/conformance/)。token と部屋コードの中身は、含めない。"""
        return {
            "phase": self.state,
            "seat": self.seat if self.players else None,
            "players": [{"seat": p["seat"], "name": p["name"]} for p in self.players],
            "room": "<room>" if self.room_code else None,
            "hasToken": bool(self.token),
            "seq": self.view_seq,
            "view": self.view,
            "events": self.view_events,
            "resync": self.view_resync,
            "relayed": [list(e) for e in self.event_log],
            "result": {"ranks": self.ranks, "why": self.why} if self.ranks is not None else None,
            "offline": sorted(self.offline_seats),
            "chat": [{"mine": mine, "name": name, "text": text} for mine, name, text in self.chat],
            "errors": list(self.errors),
            "ruleErrors": list(self.rule_errors),
        }
