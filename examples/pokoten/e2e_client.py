"""Python のクライアント(NetSession + ThreadTransport)を、本物の Workers ランタイム(wrangler dev)につないで、通しで確かめる。
  npx wrangler dev -c examples/pokoten/wrangler.jsonc --port 8787 &
  PYTHONPATH=client python examples/pokoten/e2e_client.py
"""
import sys
import time

from netgame import NetSession
from netgame.transport import ThreadTransport

GAME = "pokoten"


def mk():
    s = NetSession(ThreadTransport(), GAME)
    s.start()
    return s


def until(cond, sessions, sec=6):
    end = time.time() + sec
    while time.time() < end:
        for s in sessions:
            s.update()
        if cond():
            return
        time.sleep(0.02)
    raise SystemExit("時間切れ: " + str([(s.state, s.error) for s in sessions]))


def ok(c, msg):
    if not c:
        raise SystemExit("失敗: " + msg)
    print("ok:", msg)


a, b = mk(), mk()
until(lambda: a.state == "idle" and b.state == "idle", [a, b])
ok(a.config.get("max_players") == 2 and a.limits.get("chat") == 30, "hello(設定)")
a.register("たろう", settings={"diff": "hard"})
b.register("はなこ😀", settings={"diff": "hard"})
until(lambda: a.state == "ready" and b.state == "ready", [a, b])
ok({a.seat, b.seat} == {0, 1} and a.seed == b.seed and a.opp_name and b.opp_name, "ランダムで組まれる(席は、先に着いた順)")
a.ready()
until(lambda: b.opp_ready, [a, b])
b.ready()
until(lambda: a.state == "playing" and b.state == "playing", [a, b])
ok(True, "準備OK → start")
a.send_event("attack", {"n": 1})
until(lambda: b.events, [a, b])
ok(b.take_events() == [(a.seat, "attack", {"n": 1})], "attack が届く(席は、先に着いた順)")
a.set_pause(True)
until(lambda: b.paused_opp, [a, b])
ok(b.frozen, "一時停止が届く")
a.set_pause(False)
b.say("よろしく！")
until(lambda: a.chat, [a, b])
ok(a.chat[-1][2] == "よろしく！" and a.chat[-1][0] is False, "日本語のチャット")
a.send_event("over")
until(lambda: b.state == "over", [a, b])
ok((a.result, b.result) == ("lose", "win"), "勝敗")
a.rematch()
b.rematch()
until(lambda: a.state == "ready" and a.match_no == 2, [a, b])
ok(not a.ready_sent, "再戦で、準備OKからやり直し")

h, g = mk(), mk()
until(lambda: h.state == "idle" and g.state == "idle", [h, g])
h.register("ホスト", mode="friend", password="4321", settings={"diff": "easy"})
until(lambda: h.room_id, [h, g])
ok(len(h.room_id) == 6, "ルームIDが発行される")
g.register("ゲスト", mode="friend", password="0000", room=h.room_id)
until(lambda: g.notice, [h, g])
ok(g.notice == "pass" and g.state == "idle", "パスワード違いで入れない")
g.register("ゲスト", mode="friend", password="4321", room=h.room_id)
until(lambda: g.state == "ready", [h, g])
ok(g.settings == {"diff": "easy"}, "ルームに入れる(設定は作った人のもの)")
h.close()
until(lambda: g.state == "over", [h, g])
ok(g.result == "win" and g.opp_left and g.why == "left", "相手が切れたら勝ち")
for s in (a, b, g):
    s.close()
print("すべて ok")
sys.exit(0)
