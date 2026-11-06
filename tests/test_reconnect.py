"""Python クライアント(NetSession v=2)の、自動再接続と、登録時の扱い(JS 版 NetGameClient と同じ振る舞い)。
JS との一致そのものは、tests/conformance/ の適合テストが確かめる。ここでは、細かい場合(失敗・あきらめ・無効)を確かめる。"""
import json

from fakes import Clock, FakeTransport
from netgame.session import NetSession


class T2(FakeTransport):
    """v=2 の open(game, url, version) を受ける偽の通信。"""

    def open(self, game, url="", version=1):
        self.opened_with = (game, url, version)
        self.state, self.opened = "open", True


CONFIG = {"min_players": 2, "max_players": 2, "mode": "authoritative", "limits": {"name": 8, "chat": 30},
          "flow": {"ready": False, "rematch": "game"}, "rooms": {"code": "alnum4", "password": "none"}}


class World:
    """session と、再接続のたびに作られる偽の通信を、まとめて持つ。"""

    def __init__(self, **kw):
        self.clock = Clock()
        self.made = []
        self.t = T2()
        self.s = NetSession(self.t, "cards", self.clock, version=2, transport_factory=self._make, **kw)
        self.t.state, self.t.opened = "open", True

    def _make(self):
        t = T2()
        t.state = "connecting"
        self.made.append(t)
        return t

    def hello(self, t=None):
        t = t or self.t
        t.recv(t="hello", id="AAAA-BBBB", v=2, game="cards", config=CONFIG)
        self.s.update()

    def playing(self):
        """登録 → 対戦中(token と部屋コードを持つ)まで進める。"""
        self.hello()
        assert self.s.register("あ", mode="random")
        self.t.recv(t="registered", id="AAAA-BBBB", name="あ", token="f" * 32)
        self.t.recv(t="match", seed=1, you=0, mode="authoritative", room="AB3X", settings={},
                    players=[{"seat": 0, "name": "あ"}, {"seat": 1, "name": "い"}])
        self.t.recv(t="start")
        self.t.recv(t="state", seq=0, view={"hand": [1, 2, 3]}, events=[])
        self.s.update()
        assert self.s.state == "playing" and self.s.token and self.s.room_code == "AB3X"

    def lose_connection(self):
        self.t.close()
        self.s.update()

    def advance(self, sec):
        self.clock.t += sec
        self.s.update()


# ---- 登録時の扱い: JS 版と同じ(形は検査せず、そのまま送り、サーバーのエラーで返る) ----
def test_v2_の登録は_合言葉と部屋コードの形を検査せず_そのまま送る():
    w = World()
    w.hello()
    assert w.s.register("あ", mode="friend", room="abc", password="12")
    m = w.t.msgs()[-1]
    assert m == {"t": "register", "name": "あ", "mode": "friend", "pass": "12", "room": "abc"}
    assert w.s.state == "waiting"
    w.t.recv(t="error", code="room")                 # サーバーが断る → 登録はやり直せる
    w.s.update()
    assert (w.s.state, w.s.notice, w.s.errors) == ("idle", "room", ["room"])
    assert w.s.register("あ", mode="friend")         # 合言葉・部屋コードなしも、そのまま(部屋を作る)
    assert w.t.msgs()[-1] == {"t": "register", "name": "あ", "mode": "friend"}


def test_v2_の登録は_名前が空なら送らない_JS版と同じ():
    w = World()
    w.hello()
    sent = len(w.t.sent)
    assert w.s.register("  ", mode="random") is False
    assert w.s.register("\u0000", mode="random") is False
    assert len(w.t.sent) == sent and w.s.state == "idle"


def test_v1_の登録は_これまで通り形を検査する():
    t, clock = FakeTransport(), Clock()
    s = NetSession(t, "pokoten", clock)
    t.state, t.opened = "open", True
    t.recv(t="hello", id="AAAA-BBBB", v=1, game="pokoten", config={"limits": {}})
    s.update()
    assert s.register("あ", mode="friend", room="abc", password="12") is False and s.notice == "key"
    assert s.register("あ", mode="friend", room="abc", password="1234") is False and s.notice == "room"


# ---- 自動再接続 ----
def test_切れたら再接続の待ちに入り_その間の送信は捨てる_待ち時間のあとにつなぎ直して_resume_で戻る():
    w = World()
    w.playing()
    w.lose_connection()
    assert w.s.status == "reconnecting" and w.s.state == "playing"       # state は切れる前のまま
    assert w.s.act({"type": "play"}) is False and w.s.say("やあ") is False and w.s.send_event("stamp") is False
    assert not w.made                                                      # まだ待ち時間のうち
    w.advance(0.5)
    assert not w.made
    w.advance(20)                                                          # 待ち時間(最大 10 秒 × 1.25)を過ぎた
    assert len(w.made) == 1 and w.made[0].opened_with == ("cards", "", 2)  # 新しい接続を、v=2 で開いた
    assert w.s.act({"type": "play"}) is False                              # 開いたが、hello 前。古い盤面への操作は送らない
    assert w.made[0].msgs() == []
    w.s.t.state = "open"
    w.hello(w.made[0])
    assert w.made[0].msgs() == [{"t": "resume", "room": "AB3X", "token": "f" * 32}]
    assert (w.s.state, w.s.status) == ("resuming", "open")
    w.made[0].recv(t="resumed", id="CCCC-DDDD", you=0, room="AB3X", status="playing", mode="authoritative", settings={}, seed=1,
                   players=[{"seat": 0, "name": "あ"}, {"seat": 1, "name": "い"}])
    w.made[0].recv(t="state", seq=3, view={"hand": [2, 3]}, events=[], resync=True)
    w.s.update()
    assert w.s.state == "playing" and w.s.view == {"hand": [2, 3]} and w.s.view_resync is True
    assert w.s.act({"type": "play", "n": 2})                               # 戻ったあとは、送れる
    assert w.made[0].msgs()[-1] == {"t": "act", "a": {"type": "play", "n": 2}}


def test_戻れなかったら_idle_に戻り_notice_resume_登録しなおせる():
    w = World()
    w.playing()
    w.lose_connection()
    w.advance(20)
    t2 = w.made[0]
    t2.state = "open"
    w.hello(t2)
    t2.recv(t="error", code="resume")
    w.s.update()
    s = w.s
    assert (s.state, s.status, s.notice, s.errors) == ("idle", "open", "resume", ["resume"])
    assert (s.token, s.room_code, s.players, s.view) == ("", "", [], None)  # 対戦の状態は空(JS 版の resume_failed と同じ)
    assert s.snapshot()["seat"] is None
    assert s.register("あ", mode="random")


def test_つなぎ直しの接続が_hello_の前に閉じたら_また待つ():
    w = World()
    w.playing()
    w.lose_connection()
    w.advance(20)
    first = w.made[0]
    first.state = "closed"                          # 開く前に閉じられた
    w.s.update()
    assert w.s.status == "reconnecting" and len(w.made) == 1
    w.advance(20)
    assert len(w.made) == 2


def test_あきらめる時間を過ぎたら_closed_lost():
    w = World(reconnect={"give_up_ms": 5000, "min_ms": 100000, "max_ms": 100000})   # 待ち時間が長くて、つなぎ直せないまま過ぎる
    w.playing()
    w.lose_connection()
    w.advance(4)
    assert w.s.status == "reconnecting"
    w.advance(2)
    assert (w.s.state, w.s.status, w.s.error) == ("closed", "closed", "lost")


def test_reconnect_False_や_close_や_v1_は_再接続しない():
    w = World(reconnect=False)
    w.playing()
    w.lose_connection()
    assert (w.s.state, w.s.error) == ("closed", "lost")

    w = World()
    w.playing()
    w.s.close()
    w.advance(60)
    assert w.s.state == "closed" and w.s.error is None and not w.made

    t, clock = FakeTransport(), Clock()                       # v1 は、そもそも token がない
    s = NetSession(t, "duel", clock)
    t.state, t.opened = "open", True
    t.close()
    s.state = "playing"
    s.update()
    assert (s.state, s.error) == ("closed", "lost")


def test_部屋に入る前_token_も部屋コードもない_に切れたら_再接続せず_closed():
    w = World()
    w.hello()
    assert w.s.register("あ", mode="random")
    w.lose_connection()
    assert (w.s.state, w.s.error) == ("closed", "lost")
    assert not w.made


def test_待機中の部屋の作成者は_部屋コードがあるので戻れる():
    w = World()
    w.hello()
    assert w.s.register("あ", mode="friend")
    w.t.recv(t="registered", id="AAAA-BBBB", name="あ", token="e" * 32)
    w.t.recv(t="waiting", room="QW7K")
    w.s.update()
    assert w.s.state == "waiting" and w.s.room_code == "QW7K"
    w.lose_connection()
    assert w.s.status == "reconnecting"
    w.advance(20)
    t2 = w.made[0]
    t2.state = "open"
    w.hello(t2)
    assert t2.msgs() == [{"t": "resume", "room": "QW7K", "token": "e" * 32}]
    t2.recv(t="resumed", id="X", you=0, room="QW7K", status="waiting", mode="authoritative", settings={}, seed=None,
            players=[{"seat": 0, "name": "あ"}])
    t2.recv(t="waiting", room="QW7K")
    w.s.update()
    assert w.s.state == "waiting"


def test_status_は_JS版と同じ値():
    w = World()
    assert w.s.status == "open" or w.s.status == "connecting"
    w.playing()
    assert w.s.status == "open"
    w.lose_connection()
    assert w.s.status == "reconnecting"
    w.s.close()
    assert w.s.status == "closed"
    assert json.loads(json.dumps(w.s.snapshot()))["phase"] == "closed"
