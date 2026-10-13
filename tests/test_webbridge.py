"""ブラウザ(pygbag)とのつなぎのテスト。本物のブラウザの代わりに、偽の window を使う。"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from netgame import transport, webbridge


class Rect:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


def fake_browser(monkeypatch, js):
    import platform

    class FakeWindow:
        def eval(self, code):
            assert "ngNet" in code
            self.ngNet = js                       # 本物の JS では、eval した結果 window.ngNet ができる

    monkeypatch.setattr(platform, "window", FakeWindow(), raising=False)


def test_shim_has_no_double_underscore_names_and_no_prompt():
    assert "__" not in webbridge.SHIM.replace("__proto__", "")
    assert "window.ngNet" in webbridge.SHIM
    assert "prompt" not in webbridge.SHIM


def test_web_transport_passes_game_and_version(monkeypatch):
    """先頭が "__" の名前を Python が書き換えて、ブラウザで動かなかったことがある。偽の window で、属性名・呼び出しを確かめる。"""
    class FakeJS:
        state, opened = "connecting", False

        def __init__(self):
            self.sent, self.q = [], ["{}", "pong"]

        def open(self, url, query):
            self.args = (url, query)

        def send(self, s):
            self.sent.append(s)

        def take(self):
            r, self.q = "\n".join(self.q), []
            return r

        def close(self):
            self.state = "closed"

    fake_browser(monkeypatch, FakeJS())
    t = transport.WebTransport()
    t.open("pokoten")
    assert t.js.args == ("", "game=pokoten&v=1")
    t.send("x")
    assert t.js.sent == ["x"] and t.state == "connecting" and not t.opened
    assert t.poll() == ["{}", "pong"] and t.poll() == []
    t.close()
    assert t.state == "closed"


def test_storage_and_input_use_ascii_json(monkeypatch):
    """Python から JS へ日本語をそのまま渡すと文字化けするので、JSON(ASCII)で受け渡す。"""
    monkeypatch.setattr(webbridge, "IS_WEB", True)
    log = {"state": {"v": "", "e": False, "x": False, "c": False}}

    class FakeJS:
        def store(self, key, value):
            assert value.isascii()
            log["stored"] = json.loads(value)

        def load(self, key):
            return json.dumps(log.get("stored"))

        def fieldShow(self, x, y, w, h, font, maxlen, value, digits, invisible):
            assert value.isascii()
            log["show"] = (x, y, w, h, font, maxlen, json.loads(value), digits, invisible)

        def fieldState(self):
            return json.dumps(log["state"])

        def fieldSet(self, value):
            assert value.isascii()
            log["set"] = json.loads(value)

        def fieldHide(self):
            log["hidden"] = True

        def copy(self, value):
            assert value.isascii()
            log["copied"] = json.loads(value)
            return True

    fake_browser(monkeypatch, FakeJS())
    webbridge.storage_set("name", "はなこ")
    assert log["stored"] == "はなこ" and webbridge.storage_get("name") == "はなこ"
    w = webbridge.WebInput()
    w.show(Rect(60, 400, 360, 52), 24, 8, "あい", digits=False, invisible=True)
    assert log["show"] == (60, 400, 360, 52, 24, 8, "あい", 0, 1)
    log["state"] = {"v": "たろう", "e": True, "x": False, "c": True}
    assert w.poll() == ("たろう", True, False, True)
    w.set("さん")
    assert log["set"] == "さん"
    w.hide()
    assert log["hidden"]
    assert webbridge.copy_text("日本語 123") and log["copied"] == "日本語 123"
    assert webbridge.paste_text() == ""                       # ブラウザでは、貼り付けは入力欄が受け持つ


def test_share_url():
    assert webbridge.share_url("x", "件名", "あ b\nc").startswith("https://x.com/messages/compose?text=")
    assert webbridge.share_url("line", "件名", "あ b\nc") == "https://line.me/R/msg/text/?%E3%81%82%20b%0Ac"
    assert webbridge.share_url("mail", "件名 1", "本文") == "mailto:?subject=%E4%BB%B6%E5%90%8D%201&body=%E6%9C%AC%E6%96%87"
    assert webbridge.share_url("sms", "a", "b") == ""
    assert webbridge.page_url() == ""                         # ブラウザ以外では空


def test_storage_is_noop_outside_the_browser():
    assert webbridge.storage_get("k") is None
    webbridge.storage_set("k", "v")                           # 何も起きない


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node がない")
def test_shim_runs_in_node_with_fake_websocket(tmp_path):
    """SHIM(JS)を、偽の WebSocket・localStorage で動かして、日本語の往復・接続先・古い接続の無視を確かめる。"""
    shim = tmp_path / "shim.js"
    shim.write_text(webbridge.SHIM, encoding="utf-8")
    script = Path(__file__).with_name("shim_test.cjs")
    r = subprocess.run([NODE, str(script), str(shim)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "shim ok" in r.stdout


def test_make_transport_without_websockets(monkeypatch):
    monkeypatch.setattr(transport, "IS_WEB", False)
    monkeypatch.setattr(transport.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(RuntimeError):
        transport.make_transport()
    monkeypatch.setattr(transport.importlib.util, "find_spec", lambda name: object())
    assert isinstance(transport.make_transport(), transport.ThreadTransport)
