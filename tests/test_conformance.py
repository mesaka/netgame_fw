"""適合テスト(Python 側): シナリオ(tests/conformance/scenario.json)を、Python クライアント(NetSession v=2)で実行し、
各ステップのあとの snapshot() が golden.json と一致することを確かめる。JS クライアント(client-js/conformance.test.js)も
同じ golden と比べる = 2つのクライアントが、同じサーバーの出力を、同じ状態として解釈する。

サーバーの核は Node(tests/conformance/host.mjs)。標準入出力で1命令ずつ実行して、その場で結果を受け取るので、順序が決まっていて速い。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from netgame.protocol import PROTOCOL_VERSION
from netgame.session import NetSession
from netgame.transport import Transport

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "tests" / "conformance"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node がありません")


class Host:
    """host.mjs(サーバーの核)の子プロセス。command() は、ホストが実行し終わるまで待ち、出てきたメッセージを接続に配る。"""

    def __init__(self):
        self.p = subprocess.Popen(["node", str(DIR / "host.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, encoding="utf-8", cwd=ROOT)
        self.n = 0
        self.transports = {}

    def command(self, cmd):
        self.n += 1
        self.p.stdin.write(json.dumps({"n": self.n, **cmd}, ensure_ascii=True) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("host が終了しました")
            o = json.loads(line)
            if "ack" in o:
                assert o["ack"] == self.n
                return
            t = self.transports.get(o["c"])
            if t is None:
                continue
            if "m" in o:
                t.inbox.append(o["m"])
            else:
                t.state = "closed"

    def stop(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


class HostTransport(Transport):
    """NetSession から見た WebSocket。実際には、Host の1接続。"""

    def __init__(self, host, cid):
        self.host, self.cid = host, cid
        self.inbox = []
        self.state, self.opened = "closed", False
        host.transports[cid] = self

    def open(self, game, url="", version=PROTOCOL_VERSION):
        self.state, self.opened = "open", True
        self.host.command({"op": "open", "c": self.cid, "game": game, "v": version})

    def send(self, text):
        if text != "ping":
            self.host.command({"op": "say", "c": self.cid, "text": text})

    def poll(self):
        out, self.inbox = self.inbox, []
        return out

    def close(self):
        if self.state != "closed":
            self.state = "closed"
            self.host.command({"op": "close", "c": self.cid})


def run_scenario(host):
    sc = json.loads((DIR / "scenario.json").read_text(encoding="utf-8"))
    sessions, live, log = {}, set(), []
    clk = {"t": 0.0}                                    # 差し替えた時計(再接続の待ち時間を、テストが進める)
    made = {"n": 0}
    stores = {}                                         # 保存先(token と部屋コード)。connect の storage で、同じものを共有する(ページを開き直した想定)

    def new_transport(who):
        made["n"] += 1
        return HostTransport(host, "p%s%d" % (who, made["n"]))

    def settle():
        for _ in range(2):
            for s in sessions.values():
                s.update()

    def resolve(who, v):
        if v == "$hand0":
            return sessions[who].view["hand"][0]
        if isinstance(v, dict):
            return {k: resolve(who, x) for k, x in v.items()}
        return v

    for i, st in enumerate(sc["steps"]):
        who, do = st.get("who"), st["do"]
        s = sessions.get(who)
        expect = st.get("expect", True)
        if do == "connect":
            s = NetSession(new_transport(who), sc["game"], version=sc["v"], clock=lambda: clk["t"],
                           transport_factory=lambda who=who: new_transport(who),
                           storage=stores.setdefault(st.get("storage", who), {}))
            sessions[who] = s
            live.add(who)
            s.start()
        elif do == "registerRandom":
            assert s.register(st["name"], mode="random") == expect
        elif do == "registerFriend":
            room = st.get("room")
            if room and room.startswith("$room:"):
                room = sessions[room.split(":")[1]].room_code
            assert s.register(st["name"], mode="friend", room=room, password=st.get("pass")) == expect
        elif do == "act":
            assert s.act(resolve(who, st["a"]))
        elif do == "event":
            s.send_event(st["k"], st["d"])
        elif do == "chat":
            s.say(st["text"])
        elif do == "drop":
            s.close()
            live.discard(who)
        elif do == "netDrop":
            s.t.close()                                 # 通信が途切れた(session が気づいて、自動再接続の待ちに入る)
        elif do == "awaitReconnect":
            s.update()
            assert s.status == "reconnecting"
            for _ in range(50):
                if s.status == "open" and s.state not in ("resuming", "connecting"):
                    break
                clk["t"] += 20.0
                settle()
        elif do == "resumeSaved":
            assert s.resume()
        elif do == "leave":
            s.leave()
        elif do == "resume":
            f = sessions[st["from"]]
            assert s.resume(f.room_code, f.token)
        elif do == "playAll":
            for n in list(s.view["hand"]):
                assert s.act({"type": "play", "n": n})
                settle()
        elif do == "tick":
            host.command({"op": "tick", "ms": st["ms"]})
        elif do == "alarm":
            host.command({"op": "alarm"})
        else:
            raise AssertionError("知らない手順: " + do)
        settle()
        log.append({"step": i, "snaps": {w: sessions[w].snapshot() for w in sorted(live, key=lambda w: list(sessions).index(w))}})
    return log


def test_適合_Pythonクライアントの各ステップのsnapshotがgoldenと一致する():
    golden = json.loads((DIR / "golden.json").read_text(encoding="utf-8"))
    sc = json.loads((DIR / "scenario.json").read_text(encoding="utf-8"))["steps"]
    host = Host()
    try:
        log = run_scenario(host)
    finally:
        host.stop()
    assert len(log) == len(golden)
    for g, got in zip(golden, log):
        assert got == g, "step %d: %s" % (g["step"], json.dumps(sc[g["step"]], ensure_ascii=False))
