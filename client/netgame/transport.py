"""WebSocket の送受信(pygame非依存)。

  ブラウザ(pygbag) ... JavaScript の WebSocket を、webbridge の小さなJSで包んで使う(毎フレーム、届いたものを取り出す)。
  PC(ネイティブ)    ... `pip install websockets` が入っていれば、別スレッドで動かす。
接続先: ブラウザは、同じサイトの /ws(ページのURLに ?server=wss://… を付けると変えられる)。
        PCは、環境変数 NETGAME_SERVER(既定: ws://localhost:8787/ws。`npx wrangler dev` の既定ポート)。
どちらも、`?game=<ゲームID>&v=<版>` を付けて接続する(版は NetSession(version=…)。既定は 1)。
"""
from __future__ import annotations

import importlib
import importlib.util
import os

from .protocol import PROTOCOL_VERSION
from .webbridge import IS_WEB, bridge

NATIVE_URL = "ws://localhost:8787/ws"


class Transport:
    """WebSocket の送受信。state: "connecting" / "open" / "closed"。"""
    state = "closed"
    opened = False                  # 一度でも接続できたか(できないまま閉じたら「接続できない」)

    def open(self, game: str, url: str = "", version: int = PROTOCOL_VERSION):
        """game に接続する。url が空なら、既定の接続先。version は、プロトコルの版(v=2 の authoritative など)。"""
        raise NotImplementedError

    def send(self, text: str):
        raise NotImplementedError

    def poll(self) -> list:
        """届いたメッセージ(文字列)を、古い順に全部返す。"""
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


def query_for(game: str, version: int = PROTOCOL_VERSION) -> str:
    return "game=%s&v=%d" % (game, version)


class WebTransport(Transport):
    def __init__(self):
        self.js = bridge()

    def open(self, game, url="", version=PROTOCOL_VERSION):
        self.js.open(url, query_for(game, version))

    @property
    def state(self):
        return str(self.js.state)

    @property
    def opened(self):
        return bool(self.js.opened)

    def send(self, text):
        self.js.send(text)

    def poll(self):
        s = str(self.js.take())
        return s.split("\n") if s else []

    def close(self):
        self.js.close()


class ThreadTransport(Transport):
    """PC用。websockets の同期クライアントを別スレッドで動かす。"""

    def __init__(self):
        import queue
        import threading
        self._queue, self._threading = queue, threading        # ブラウザ版では使わないので、ここで読む
        self.state = "closed"
        self.opened = False
        self._in = queue.Queue()
        self._out = queue.Queue()
        self._stop = threading.Event()

    def open(self, game, url="", version=PROTOCOL_VERSION):
        self.state = "connecting"
        base = url or os.environ.get("NETGAME_SERVER", NATIVE_URL)
        full = base + ("&" if "?" in base else "?") + query_for(game, version)
        self._threading.Thread(target=self._run, args=(full,), daemon=True).start()

    def _run(self, url):
        try:
            # 文字列で読む(pygbag のビルドが、ブラウザでは使えない websockets を探しに行かないように)
            connect = importlib.import_module("websockets.sync.client").connect
            with connect(url, open_timeout=8, max_size=1 << 16) as ws:
                self.state, self.opened = "open", True
                while not self._stop.is_set():
                    try:
                        while True:
                            ws.send(self._out.get_nowait())
                    except self._queue.Empty:
                        pass
                    try:
                        self._in.put(ws.recv(timeout=0.03))
                    except TimeoutError:
                        pass
        except Exception as e:                          # noqa: BLE001  (接続失敗・切断・websockets なし)
            print("net:", repr(e))
        self.state = "closed"

    def send(self, text):
        self._out.put(text)

    def poll(self):
        out = []
        while True:
            try:
                m = self._in.get_nowait()
            except self._queue.Empty:
                return out
            if isinstance(m, str):
                out.append(m)

    def close(self):
        self._stop.set()


def make_transport() -> Transport:
    if IS_WEB:
        return WebTransport()
    if importlib.util.find_spec("websockets") is None:
        raise RuntimeError("websockets が入っていません (pip install websockets)")
    return ThreadTransport()
