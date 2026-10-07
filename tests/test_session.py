"""NetSession(通信の状態機械)のテスト。mesaka/pokoten の test_net.py の内容を、v1 の通信・席・順位の形で移したもの。"""
import json

import pytest

from fakes import Clock, FakeTransport
from netgame import protocol
from netgame.session import NetSession

CONFIG = {"min_players": 2, "max_players": 2, "mode": "realtime", "limits": {"name": 8, "chat": 30}}


def session(game="pokoten"):
    t, clock = FakeTransport(), Clock()
    s = NetSession(t, game, clock)
    t.state, t.opened = "open", True
    return s, t, clock


def hello(s, t, **kw):
    t.recv(t="hello", id="AAAA-BBBB", v=1, game=s.game, config={**CONFIG, **kw})
    s.update()


def match(t, seed=123, you=0, mode="realtime", names=("たろう", "はなこ"), settings=None):
    t.recv(t="match", seed=seed, you=you, mode=mode, settings=settings or {"diff": "hard"},
           players=[{"seat": i, "name": n} for i, n in enumerate(names)])


def to_ready(s, t, **kw):
    hello(s, t)
    assert s.state == "idle"
    assert s.register("たろう", settings={"diff": "hard"})
    match(t, **kw)
    s.update()


def to_playing(s, t, **kw):
    """マッチして、双方が準備OKを押して、対戦が始まった状態。"""
    to_ready(s, t, **kw)
    s.ready()
    turn = {"seat": 0, "seq": 0} if kw.get("mode") == "turns" else None
    t.recv(t="start", **({"turn": turn} if turn else {}))
    s.update()


def test_open_connects_to_the_game():
    s, t, _ = session("duel")
    s.start()
    assert t.opened_with == ("duel", "")


def test_flow_hello_register_match():
    s, t, _ = session()
    assert s.state == "connecting"
    hello(s, t)
    assert (s.state, s.conn_id) == ("idle", "AAAA-BBBB")
    assert s.config["max_players"] == 2 and s.limits["chat"] == 30
    assert not s.register("   ")                         # 空の名前は送らない
    assert s.register("たろう" * 5, settings={"diff": "hard"})
    assert t.msgs() == [{"t": "register", "name": "たろうたろうたろう"[:8], "mode": "random", "settings": {"diff": "hard"}}]
    assert s.state == "waiting"
    match(t, seed=7, you=1, names=("はなこ", "たろう"))
    s.update()
    assert (s.state, s.seed, s.seat, s.opp_name, s.match_no) == ("ready", 7, 1, "はなこ", 1)     # まず準備OK待ち
    assert [p["name"] for p in s.players] == ["はなこ", "たろう"] and s.settings == {"diff": "hard"}


def test_version_mismatch_and_unknown_game_close_the_session():
    s, t, _ = session()
    t.recv(t="hello", id="X", v=2, game="pokoten", config=CONFIG)
    s.update()
    assert (s.state, s.error) == ("closed", "version")
    s, t, _ = session("nope")
    t.recv(t="error", code="game")
    s.update()
    assert (s.state, s.error) == ("closed", "game")


def test_messages_are_ascii_only():
    s, t, _ = session()
    to_playing(s, t)
    s.say("よろしく！")
    assert all(x.isascii() for x in t.sent)
    assert t.msgs()[-1] == {"t": "chat", "text": "よろしく！"}


def test_ready_then_start():
    s, t, _ = session()
    to_ready(s, t)
    s.send_event("attack", {"n": 1})
    s.report_finish([{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}])      # 準備中は、ゲームの通信は送らない
    assert t.msgs()[-1]["t"] == "register"
    s.ready()
    s.ready()
    assert [m["t"] for m in t.msgs()].count("ready") == 1 and s.state == "ready"
    t.recv(t="ready_state", seats=[1])
    s.update()
    assert s.opp_ready and s.ready_sent
    t.recv(t="start")
    s.update()
    assert (s.state, s.start_no) == ("playing", 1)
    s.send_event("attack", {"n": 1})
    assert t.msgs()[-1] == {"t": "event", "k": "attack", "d": {"n": 1}}


def test_ready_flag_is_sticky_even_if_the_same_match_arrives_again():
    s, t, _ = session()
    to_ready(s, t)
    s.ready()
    assert s.ready_sent
    t.recv(t="chat", seat=1, name="はなこ", text="よろしく")
    match(t)                                                                # 同じ組み合わせ
    s.update()
    assert s.ready_sent and s.state == "ready" and s.match_no == 1
    match(t, seed=999)                                                      # 新しい対戦なら、やり直し
    s.update()
    assert not s.ready_sent and s.match_no == 2


def test_realtime_events_and_result():
    s, t, _ = session()
    to_playing(s, t)
    t.recv(t="event", seat=1, k="attack", d={"n": 1})
    t.recv(t="event", seat=1, k="attack", d={"n": 2})
    t.recv(t="event", seat=1, k="snap", d={"b": "x"})
    s.update()
    assert s.take_events() == [(1, "attack", {"n": 1}), (1, "attack", {"n": 2}), (1, "snap", {"b": "x"})]
    assert s.take_events() == []
    s.send_event("over")
    assert t.msgs()[-1] == {"t": "event", "k": "over", "d": {}}
    t.recv(t="result", ranks=[{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}], why="normal")
    s.update()
    assert (s.state, s.result, s.my_rank, s.why) == ("over", "lose", 2, "normal")
    s.send_event("attack", {"n": 1})                                        # 決着後は何も送らない
    assert t.msgs()[-1] == {"t": "event", "k": "over", "d": {}}


def test_result_win_and_draw():
    s, t, _ = session()
    to_playing(s, t)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}], why="normal")
    s.update()
    assert s.result == "win"
    s, t, _ = session()
    to_playing(s, t)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 1}], why="abort")
    s.update()
    assert s.result == "draw"


def test_rematch_and_new_match_resets():
    s, t, _ = session()
    to_playing(s, t)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}], why="normal")
    s.update()
    s.rematch()
    s.rematch()
    assert [m["t"] for m in t.msgs()].count("rematch") == 1
    t.recv(t="rematch_req", seat=1)
    s.update()
    assert s.opp_wants_rematch
    match(t, seed=8)
    s.update()
    assert (s.state, s.ranks, s.match_no, s.rematch_sent, s.ready_sent) == ("ready", None, 2, False, False)


def test_chat_log_marks_mine_and_clips():
    s, t, _ = session()
    to_playing(s, t)
    t.recv(t="chat", seat=0, name="たろう", text="あ" * 50)
    t.recv(t="chat", seat=1, name="はなこ", text="こんにちは")
    s.update()
    assert [(m[0], len(m[2])) for m in s.chat] == [(True, 30), (False, 5)]
    assert s.unread_chat == 2


def test_chat_is_refused_outside_a_match_but_allowed_while_getting_ready():
    s, t, _ = session()
    hello(s, t)
    assert not s.say("こんにちは")
    s.register("たろう")
    match(t)
    s.update()
    assert s.say("よろしくお願いします。")
    assert t.msgs()[-1]["t"] == "chat" and not s.sent_end_chat              # 「決着後の最初の1通」には数えない
    assert not s.say("   ")


def test_opponent_leaving():
    s, t, clock = session()
    to_playing(s, t)
    clock.t = 10
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}], why="left")
    s.update()
    assert (s.result, s.opp_left) == ("win", True) and s.leave_left() == protocol.LEAVE_TIMEOUT
    clock.t = 35
    assert s.leave_left() == protocol.LEAVE_TIMEOUT - 25
    s.rematch()
    assert "rematch" not in [m["t"] for m in t.msgs()]
    s2, t2, clock2 = session()
    to_playing(s2, t2)
    assert s2.leave_left() is None
    t2.recv(t="result", ranks=[{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}], why="normal")
    s2.update()
    clock2.t = 50
    t2.recv(t="player_left", seat=1)                                         # 決着後に退出した場合も同じ
    s2.update()
    assert s2.leave_left() == protocol.LEAVE_TIMEOUT and not s2.say("もう一言")


def test_opponent_leaving_while_getting_ready_is_a_win():
    s, t, _ = session()
    to_ready(s, t)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}], why="left")
    s.update()
    assert (s.state, s.result, s.opp_left) == ("over", "win", True)


def test_connection_failures():
    s, t, clock = session()
    t.state, t.opened = "closed", False
    s.update()
    assert (s.state, s.error) == ("closed", "connect")
    s, t, clock = session()
    to_playing(s, t)
    t.state = "closed"
    s.update()
    assert (s.state, s.error) == ("closed", "lost")
    s, t, clock = session()                                                  # hello が来ないまま時間切れ
    clock.t = protocol.CONNECT_TIMEOUT + 1
    s.update()
    assert (s.state, s.error) == ("closed", "connect")


def test_ping_keeps_connection_alive():
    s, t, clock = session()
    hello(s, t)
    clock.t = protocol.PING_INTERVAL + 1
    s.update()
    assert t.sent == ["ping"]
    s.update()
    assert t.sent == ["ping"]


def test_pong_and_garbage_input_are_ignored():
    s, t, _ = session()
    t.inbox += ["pong", "{broken", "[1,2]", json.dumps({"t": "unknown"}), json.dumps({"t": "_on_hello"}),
                json.dumps({"t": "__class__"})]
    s.update()
    assert s.state == "connecting"


def test_room_register_messages():
    s, t, _ = session()
    hello(s, t)
    assert not s.register("たろう", mode="friend", password="12")            # 4桁の数字でなければ送らない
    assert s.notice == "key" and s.state == "idle"
    assert not s.register("たろう", mode="friend", password="0427", room="123")
    assert s.notice == "room"
    assert s.register("たろう", mode="friend", password="0427", room="123456")   # 既存のルームに入る
    assert t.msgs()[-1] == {"t": "register", "name": "たろう", "mode": "friend", "pass": "0427", "room": "123456"}
    t.recv(t="error", code="pass")                                           # パスワード違い → 登録前に戻ってやり直せる
    s.update()
    assert (s.state, s.notice, s.error) == ("idle", "pass", None)
    assert s.register("たろう", mode="friend", password="0428")              # ルームを作る(ルームIDはサーバーが発行)
    assert t.msgs()[-1]["pass"] == "0428" and "room" not in t.msgs()[-1] and s.notice is None
    t.recv(t="waiting", room="654321")
    s.update()
    assert (s.room_id, s.password) == ("654321", "0428")
    match(t, seed=1)
    s.update()
    assert (s.state, s.mode) == ("ready", "friend")


def test_registration_errors_return_to_idle():
    for code in ("name", "key", "room", "pass"):
        s, t, _ = session()
        hello(s, t)
        s.register("a")
        t.recv(t="error", code=code)
        s.update()
        assert (s.state, s.notice) == ("idle", code)


def test_pause_is_shared_and_expires():
    s, t, clock = session()
    to_ready(s, t)
    s.set_pause(True)                                                        # 準備中は止めない(送らない)
    assert not s.paused_me and t.msgs()[-1]["t"] == "register"
    s.ready(); t.recv(t="start"); s.update()
    s.set_pause(True)
    s.set_pause(True)
    assert t.msgs()[-1] == {"t": "pause", "on": True} and s.frozen and s.paused_me
    assert [m["t"] for m in t.msgs()].count("pause") == 1
    clock.t = 12
    assert s.pause_age == 12
    s.set_pause(False)
    assert t.msgs()[-1] == {"t": "pause", "on": False} and not s.frozen
    t.recv(t="paused", seat=1, on=True)
    s.update()
    assert s.paused_opp and s.frozen and not s.paused_me
    clock.t += protocol.PAUSE_MAX + 11                                       # 相手の「再開」が届かなくても、止めっぱなしにしない
    s.update()
    assert not s.paused_opp
    t.recv(t="paused", seat=1, on=True)
    s.update()
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}], why="normal")   # 決着したら止めは解除
    s.update()
    assert not s.frozen


def test_idle_timeout_after_free_time():
    s, t, clock = session()
    to_playing(s, t)
    clock.t = 100
    t.recv(t="result", ranks=[{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}], why="normal")
    s.update()
    assert s.state == "over" and s.idle_left() is None
    clock.t = 100 + protocol.FREE_TIME - 1                                   # 自由時間(3分)の間は、何もしなくても退出にならない
    s.update()
    assert s.state == "over" and s.idle_left() is None                       # 警告もまだ出ない
    clock.t = 100 + protocol.FREE_TIME + 10                                  # 自由時間が過ぎた。あと20秒の警告
    s.update()
    assert 19 < s.idle_left() < 21 and s.state == "over"
    s.say("ありがとうございました。")                                        # 操作すると延びる
    assert s.idle_left() is None or s.idle_left() > 29
    clock.t += protocol.IDLE_GRACE - 1
    s.update()
    assert s.state == "over"
    clock.t += 2                                                             # 何も操作がなければ、退出
    s.update()
    assert (s.state, s.error) == ("closed", "timeout")


def test_idle_clock_is_extended_by_chat_and_rematch_but_not_when_opponent_left():
    s, t, clock = session()
    to_playing(s, t)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}], why="normal")
    s.update()
    clock.t = protocol.FREE_TIME + 25
    t.recv(t="chat", seat=1, name="はなこ", text="ありがとう！")             # 相手のチャットも「操作」
    s.update()
    assert s.idle_left() is None or s.idle_left() > 29
    clock.t += protocol.IDLE_GRACE + 5
    t.recv(t="rematch_req", seat=1)
    s.update()
    assert s.state == "over"
    t.recv(t="player_left", seat=1)
    s.update()
    clock.t += 1000
    s.update()
    assert s.state == "over" and s.idle_left() is None                       # 相手が退出済みなら、時間切れの対象にしない


# ---- turns ----
def test_turns_flow_my_turn_action_sync_finish():
    s, t, _ = session("ttt")
    to_playing(s, t, mode="turns", names=("あ", "い"))
    assert s.game_mode == "turns" and s.turn == {"seat": 0, "seq": 0} and s.my_turn
    s.send_event("hit")                                                      # turns では event は送らない
    assert t.msgs()[-1]["t"] == "ready"
    assert s.send_action({"x": 1})
    assert t.msgs()[-1] == {"t": "action", "seq": 0, "d": {"x": 1}}
    t.recv(t="action", seat=0, seq=0, d={"x": 1})                            # 自分の手も、サーバーから返ってから適用する
    t.recv(t="turn", seat=1, seq=1)
    s.update()
    assert s.take_actions() == [(0, 0, {"x": 1})]
    assert not s.my_turn and not s.send_action({"x": 2})                     # 手番ではない
    s.send_sync(0, "h" * 100)
    assert t.msgs()[-1] == {"t": "sync", "seq": 0, "h": "h" * 64}
    t.recv(t="action", seat=1, seq=1, d={"x": 2})
    t.recv(t="turn", seat=0, seq=2)
    s.update()
    assert s.my_turn and s.turn["seq"] == 2
    ranks = [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}]
    assert not s.report_finish([{"seat": 0, "rank": 1}])                     # 形が合わない順位は送らない
    assert s.report_finish(ranks)
    assert t.msgs()[-1] == {"t": "finish", "ranks": ranks}


def test_turns_desync():
    s, t, _ = session("ttt")
    to_playing(s, t, mode="turns", names=("あ", "い"))
    t.recv(t="desync", seq=3)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 1}], why="desync")
    s.update()
    assert (s.desync_seq, s.why, s.result) == (3, "desync", "draw")


def test_three_players_seats_and_names():
    s, t, _ = session("trio")
    hello(s, t, min_players=3, max_players=3)
    s.register("c")
    match(t, you=2, names=("a", "b", "c"))
    s.update()
    assert s.seat == 2 and [p["name"] for p in s.others] == ["a", "b"]
    t.recv(t="ready_state", seats=[0, 1])
    s.update()
    assert s.ready_seats == {0, 1} and s.opp_ready
    s.ready()
    t.recv(t="start")
    t.recv(t="paused", seat=0, on=True)
    t.recv(t="paused", seat=1, on=True)
    s.update()
    assert s.paused_seats == {0, 1} and s.frozen
    t.recv(t="paused", seat=0, on=False)
    s.update()
    assert s.frozen
    t.recv(t="paused", seat=1, on=False)
    s.update()
    assert not s.frozen
    t.recv(t="result", ranks=[{"seat": 0, "rank": 2}, {"seat": 1, "rank": 3}, {"seat": 2, "rank": 1}], why="normal")
    s.update()
    assert s.result == "win" and s.my_rank == 1


def test_protocol_helpers():
    assert protocol.clean_digits("0427", 4) == "0427"
    for bad in ("427", "04277", "04a7", "０４２７", "", None):
        assert protocol.clean_digits(bad, 4) == ""
    ok = [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}]
    assert protocol.valid_ranks(ok, 2) and protocol.winners(ok) == [0] and protocol.rank_of(ok, 1) == 2
    for bad in ([], [{"seat": 0, "rank": 1}], [{"seat": 0, "rank": 1}, {"seat": 0, "rank": 2}],
                [{"seat": 0, "rank": 0}, {"seat": 1, "rank": 1}], [{"seat": 0, "rank": True}, {"seat": 1, "rank": 1}],
                [{"seat": 0, "rank": 1}, {"seat": 5, "rank": 2}], "x", None):
        assert not protocol.valid_ranks(bad, 2)
