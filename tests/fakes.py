"""テスト用の偽物(偽の通信・偽の時計)。"""
import json

from netgame.transport import Transport


class FakeTransport(Transport):
    def __init__(self):
        self.state = "connecting"
        self.opened = False
        self.sent = []
        self.inbox = []
        self.opened_with = None

    def open(self, game, url=""):
        self.opened_with = (game, url)

    def send(self, text):
        self.sent.append(text)

    def poll(self):
        out, self.inbox = self.inbox, []
        return out

    def close(self):
        self.state = "closed"

    def recv(self, **m):
        self.inbox.append(json.dumps(m, ensure_ascii=False))

    def msgs(self):
        return [json.loads(s) for s in self.sent if s != "ping"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t
