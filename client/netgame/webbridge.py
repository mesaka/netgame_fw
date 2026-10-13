"""ブラウザ(pygbag)とのつなぎ(pygame非依存)。

  JavaScript 側は、小さなJS(SHIM)で包んで使う。**Python の日本語の文字列は、そのまま JS に渡すと文字化けする**ので、
  日本語を含むものは、JSON(\\uXXXX の ASCII)にして受け渡す。JS 側の名前(window.ngNet)の先頭を "__" にしない
  (Python のクラスの中で、名前が書き換えられてしまうため)。

  WebInput ... ゲーム画面の上に重ねるブラウザの入力欄(日本語入力・貼り付け・スマホのキーボードがそのまま使える)
  copy_text / paste_text / storage_get / storage_set ... クリップボード・ブラウザの保存
"""
from __future__ import annotations

import json
import sys

IS_WEB = sys.platform == "emscripten"

SHIM = r"""
(function () {
  if (window.ngNet) return;
  var N = window.ngNet = {ws: null, q: [], state: "closed", opened: false};
  function ascii(s) {
    return s.replace(/[\u0080-￿]/g, function (c) { return "\\u" + ("0000" + c.charCodeAt(0).toString(16)).slice(-4); });
  }
  // url が空なら、同じサイトの /ws(ページのURLに ?server=wss://… を付けると、接続先を変えられる)。query(game=…&v=1)を付けて接続する
  N.open = function (url, query) {
    N.q = []; N.opened = false; N.state = "connecting";
    if (!url) {
      var q = new URLSearchParams(location.search).get("server");
      url = q || ((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    }
    if (query) url += (url.indexOf("?") < 0 ? "?" : "&") + query;
    try {
      var ws = N.ws = new WebSocket(url);
      ws.onopen = function () { if (N.ws === ws) { N.state = "open"; N.opened = true; } };
      ws.onmessage = function (e) { if (N.ws === ws && typeof e.data === "string") N.q.push(ascii(e.data)); };
      ws.onclose = function () { if (N.ws === ws) N.state = "closed"; };
      ws.onerror = function () { if (N.ws === ws) N.state = "closed"; };
    } catch (e) { N.state = "closed"; }
  };
  N.send = function (s) { try { if (N.ws && N.state === "open") N.ws.send(s); } catch (e) {} };
  N.take = function () { var r = N.q.join("\n"); N.q = []; return r; };
  // 日本語を含む文字列は、JSON(ASCII のみ)にして受け渡す。Python から日本語をそのまま JS へ渡すと文字化けする
  N.store = function (key, json) { try { localStorage.setItem(key, JSON.parse(json)); } catch (e) {} };
  N.load = function (key) {
    var r = null;
    try { r = localStorage.getItem(key); } catch (e) {}
    return ascii(JSON.stringify(r));
  };
  // ---- ゲーム画面の上に重ねる入力欄(日本語入力・貼り付け・スマホのキーボードが、そのまま使える) ----
  // 位置・大きさは、ゲーム画面の座標(Python側の Rect)で受け取り、canvas の見た目の大きさに合わせて置く。
  var F = N.f = {el: null, x: 0, y: 0, w: 0, h: 0, font: 20, flags: {e: false, x: false}, composing: false};
  function place() {
    var el = F.el, c = document.getElementById("canvas");
    if (!el || !c) return;
    var r = c.getBoundingClientRect(), sx = r.width / (c.width || r.width), sy = r.height / (c.height || r.height);
    var s = el.style;
    s.left = (r.left + F.x * sx) + "px"; s.top = (r.top + F.y * sy) + "px";
    s.width = (F.w * sx) + "px"; s.height = (F.h * sy) + "px";
    s.fontSize = (F.font * sy) + "px"; s.paddingLeft = (12 * sx) + "px";
  }
  N.fieldShow = function (x, y, w, h, font, maxlen, json, digits, invisible) {
    var el = F.el;
    if (!el) {
      el = F.el = document.createElement("input");
      el.type = "text"; el.autocomplete = "off"; el.autocapitalize = "off"; el.spellcheck = false;
      var s = el.style;
      s.position = "fixed"; s.zIndex = "20"; s.boxSizing = "border-box"; s.border = "0"; s.outline = "0";
      s.background = "transparent"; s.margin = "0"; s.padding = "0";
      s.fontFamily = '"M PLUS Rounded 1c", "Hiragino Maru Gothic ProN", "Yu Gothic", sans-serif'; s.fontWeight = "700";
      // ゲーム側(SDL)が、ここで打った文字を横取りしたり、ゲームの操作として受け取ったりしないようにする
      ["keydown", "keyup", "keypress", "mousedown", "mouseup", "touchstart", "touchend", "click"].forEach(function (n) {
        el.addEventListener(n, function (e) { e.stopPropagation(); });
      });
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.isComposing) F.flags.e = true;
        else if (e.key === "Escape") F.flags.x = true;
      });
      el.addEventListener("compositionstart", function () { F.composing = true; });
      el.addEventListener("compositionend", function () { F.composing = false; });
      document.body.appendChild(el);
    }
    F.x = x; F.y = y; F.w = w; F.h = h; F.font = font; F.flags = {e: false, x: false}; F.composing = false;
    el.maxLength = maxlen; el.value = JSON.parse(json);
    el.inputMode = digits ? "numeric" : "text";
    el.style.color = invisible ? "transparent" : "#e6e8f5";
    el.style.caretColor = invisible ? "transparent" : "#ffe278";
    el.style.display = "block";
    place();
    try { el.focus(); } catch (e) {}
  };
  N.fieldState = function () {
    place();
    var el = F.el, f = F.flags;
    F.flags = {e: false, x: false};
    return ascii(JSON.stringify({v: el ? el.value : "", e: f.e, x: f.x, c: F.composing}));
  };
  N.fieldSet = function (json) { if (F.el) F.el.value = JSON.parse(json); };
  N.fieldHide = function () {
    if (F.el) { F.el.style.display = "none"; try { F.el.blur(); } catch (e) {} }
    F.composing = false;
  };
  N.copy = function (json) {
    var text = JSON.parse(json);
    try { navigator.clipboard.writeText(text); return true; } catch (e) {}
    try {                                   // 古いブラウザ・http 用
      var t = document.createElement("textarea");
      t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.select();
      var ok = document.execCommand("copy"); document.body.removeChild(t); return ok;
    } catch (e) { return false; }
  };
  // 別のタブ・アプリで開く(X・LINE のURL)。mailto: は、いまのページを離れずにメールアプリを開く。開けたら true
  N.openUrl = function (json) {
    var u = JSON.parse(json);
    try {
      if (/^mailto:/i.test(u)) { window.location.href = u; return true; }
      return !!window.open(u, "_blank");
    } catch (e) { return false; }
  };
  N.pageUrl = function () { return ascii(window.location.origin + window.location.pathname); };
  N.close = function () { try { if (N.ws) { var w = N.ws; N.ws = null; w.close(); } } catch (e) {} N.state = "closed"; };
})();
"""


def bridge():
    """JS 側の窓口(window.ngNet)。ブラウザ以外では使えない。"""
    from platform import window                      # pygbag の JS 橋渡し
    window.eval(SHIM)
    return window.ngNet                              # 先頭が "__" の名前は使わない(Python が書き換えてしまう)


class WebInput:
    """ゲーム画面の上に重ねるブラウザの入力欄(1つだけ)。show で出して、毎フレーム poll で中身を読む。
    入力欄の位置・大きさは、ゲーム画面の座標の Rect(x, y, w, h を持つもの)で渡す。"""

    def __init__(self):
        self.js = bridge()

    def show(self, rect, size, maxlen, value="", digits=False, invisible=False):
        self.js.fieldShow(int(rect.x), int(rect.y), int(rect.w), int(rect.h), int(size), int(maxlen),
                          json.dumps(value), 1 if digits else 0, 1 if invisible else 0)

    def poll(self):
        """(いまの文字, Enterが押された, Escが押された, 変換中か)"""
        r = json.loads(str(self.js.fieldState()))
        return str(r.get("v", "")), bool(r.get("e")), bool(r.get("x")), bool(r.get("c"))

    def set(self, text):
        self.js.fieldSet(json.dumps(text))

    def hide(self):
        self.js.fieldHide()


def storage_get(key):
    """ブラウザの保存(localStorage)から読む。なければ None。ブラウザ以外は常に None。"""
    if not IS_WEB:
        return None
    try:
        v = json.loads(str(bridge().load(key)))
        return v if isinstance(v, str) else None
    except Exception:                                # noqa: BLE001
        return None


def storage_set(key, value):
    if IS_WEB:
        try:
            bridge().store(key, json.dumps(value))
        except Exception:                            # noqa: BLE001
            pass


def copy_text(text) -> bool:
    """クリップボードにコピーする。できたら True。"""
    try:
        if IS_WEB:
            return bool(bridge().copy(json.dumps(text)))
        import pygame.scrap
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        pygame.scrap.put_text(text)
        return True
    except Exception as e:                           # noqa: BLE001
        print("copy:", repr(e))
        return False


def share_url(kind, subject, body) -> str:
    """招待を送るURL。kind: "x"(X のDM作成) / "line" / "mail"。送り先は、開いた先で選ぶ。知らない kind は ""。"""
    from urllib.parse import quote
    b = quote(body, safe="")
    if kind == "x":
        return "https://x.com/messages/compose?text=" + b
    if kind == "line":
        return "https://line.me/R/msg/text/?" + b
    if kind == "mail":
        return "mailto:?subject=%s&body=%s" % (quote(subject, safe=""), b)
    return ""


def open_url(url) -> bool:
    """URL(https: / mailto:)を、ブラウザ・メールアプリなどで開く。開けたら True。"""
    try:
        if IS_WEB:
            return bool(bridge().openUrl(json.dumps(url)))
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception as e:                           # noqa: BLE001
        print("open_url:", repr(e))
        return False


def page_url() -> str:
    """いま開いているページのURL(ブラウザだけ。招待の文面に添える)。それ以外は ""。"""
    try:
        return str(bridge().pageUrl()) if IS_WEB else ""
    except Exception as e:                           # noqa: BLE001
        print("page_url:", repr(e))
        return ""


def paste_text() -> str:
    """クリップボードの文字(PCだけ。ブラウザは、画面に重ねた入力欄が貼り付けを受け持つ)。"""
    if IS_WEB:
        return ""
    try:
        import pygame.scrap
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        t = pygame.scrap.get_text()
        return t if isinstance(t, str) else ""
    except Exception:                                # noqa: BLE001
        return ""
