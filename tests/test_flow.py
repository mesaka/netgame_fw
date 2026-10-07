"""NetGameScene(画面の流れ)のテスト。偽の通信と、画面なしの pygame で動かす。mesaka/pokoten の Net 場面の動作を移したもの。"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from demo_adapter import DemoAdapter
from fakes import FakeTransport
from netgame.flow import NetGameScene
from netgame.protocol import PAUSE_MAX


@pytest.fixture(scope="module", autouse=True)
def _pygame():
    pygame.init()
    pygame.display.set_mode((480, 800))
    yield
    pygame.quit()


class FakeWeb:
    """画面に重ねるブラウザの入力欄の偽物。"""

    def __init__(self):
        self.shown = None
        self.text = ""
        self.entered = self.escaped = self.composing = False
        self.hidden = 0

    def show(self, rect, size, maxlen, value="", digits=False, invisible=False):
        self.shown = (tuple(rect), size, maxlen, digits, invisible)
        self.text = value

    def poll(self):
        e, x = self.entered, self.escaped
        self.entered = self.escaped = False
        return self.text, e, x, self.composing

    def set(self, text):
        self.text = text

    def hide(self):
        self.shown = None
        self.hidden += 1


CONFIG = {"min_players": 2, "max_players": 2, "mode": "realtime", "limits": {"name": 8, "chat": 30}}


def make(adapter=None, web=None, native=True):
    t = FakeTransport()
    t.state, t.opened = "open", True
    a = adapter or DemoAdapter()
    sc = NetGameScene(a, transport=t, web_input=web, native=native)
    return sc, t, a


def hello(sc, t):
    t.recv(t="hello", id="AAAA-BBBB", v=1, game="demo", config=CONFIG)
    sc.update()


def key(sc, k, **kw):
    return sc.handle(pygame.event.Event(pygame.KEYDOWN, key=k, mod=kw.get("mod", 0), unicode=kw.get("unicode", "")))


def type_text(sc, text):
    for ch in text:
        sc.handle(pygame.event.Event(pygame.TEXTINPUT, text=ch))


def click(sc, name):
    """ボタンを押して離し、光る時間が終わるまで update する。戻り値は update の返した値。"""
    rects = sc._pad_rects()
    pos = rects[name].center
    sc.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
    sc.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
    r = None
    for _ in range(sc.pad.PRESS_FRAMES + 1):
        r = sc.update() or r
    return r


def idle(sc, t):
    hello(sc, t)
    assert sc.phase == "idle"
    assert sc.name_field is not None


def to_ready(sc, t, seat=0):
    idle(sc, t)
    type_text(sc, "Taro")
    key(sc, pygame.K_RETURN)
    t.recv(t="match", seed=77, you=seat, mode="realtime", settings={"diff": "normal"},
           players=[{"seat": 0, "name": "Taro" if seat == 0 else "Hana"}, {"seat": 1, "name": "Hana" if seat == 0 else "Taro"}])
    sc.update()


def to_playing(sc, t):
    to_ready(sc, t)
    click(sc, "ready")
    t.recv(t="ready_state", seats=[0, 1])
    t.recv(t="start")
    sc.update()
    for _ in range(sc.COUNTDOWN + 1):
        sc.update()


def sent(t, kind):
    return [m for m in t.msgs() if m.get("t") == kind]


# ---------------------------------------------------------------- 名前・相手さがし
def test_connect_then_ask_name():
    sc, t, a = make()
    assert sc.phase == "connecting"
    assert a.bgms == ["menu"]
    hello(sc, t)
    assert sc.phase == "idle"
    assert sc.name_field is not None and not sc.name_field.external


def test_random_match_registers_with_settings_and_saves_name():
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    key(sc, pygame.K_RETURN)
    reg = sent(t, "register")[0]
    assert reg["name"] == "Taro" and reg["mode"] == "random" and reg["settings"] == {"diff": "normal"}
    assert a.saved_name == "Taro"
    assert sc.phase == "waiting"


def test_saved_name_is_prefilled():
    ad = DemoAdapter()
    ad.saved_name = "Hana"
    sc, t, _ = make(ad)
    idle(sc, t)
    assert sc.name_field.text == "Hana"


def test_empty_name_asks_again():
    sc, t, a = make()
    idle(sc, t)
    key(sc, pygame.K_RETURN)
    assert sc.phase == "idle" and sc.sess.notice == "name"
    assert not sent(t, "register")


def test_cancel_while_waiting_leaves():
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    click(sc, "go")
    assert sc.phase == "waiting"
    assert click(sc, "back") == "menu"
    assert sc.sess.state == "closed"


def test_escape_in_name_field_leaves():
    sc, t, a = make()
    idle(sc, t)
    assert key(sc, pygame.K_ESCAPE) == "menu"


def test_error_screen_and_reconnect():
    sc, t, a = make()
    t.state, t.opened = "closed", False
    sc.update()
    assert sc.phase == "error" and sc.error == "connect"
    t2 = FakeTransport()
    sc._transport = t2
    click(sc, "go")
    assert sc.sess is not None and sc.phase == "connecting"


def test_native_without_websockets_shows_setup_error():
    class Boom(FakeTransport):
        def open(self, *a, **k):
            raise RuntimeError("no websockets")
    a = DemoAdapter()
    sc = NetGameScene(a, transport=Boom(), native=True)
    assert sc.phase == "error" and sc.error in ("native", "setup") and "no websockets" in sc.error_detail


# ---------------------------------------------------------------- ルーム(テンキー)
def test_make_room_with_keypad():
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    click(sc, "make")
    assert sc.keypad == "make"
    for d in "1234":
        click(sc, "k" + d)
    assert sc.digits == "1234"
    click(sc, "kdel")
    assert sc.digits == "123"
    click(sc, "k4")
    click(sc, "kok")
    reg = sent(t, "register")[0]
    assert reg["mode"] == "friend" and reg["pass"] == "1234" and "room" not in reg


def test_make_room_needs_name():
    sc, t, a = make()
    idle(sc, t)
    click(sc, "make")
    assert sc.keypad is None and sc.sess.notice == "name"


def test_join_room_two_steps_by_keyboard():
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    click(sc, "join")
    assert sc.keypad == "room"
    for d in "123456":
        key(sc, getattr(pygame, "K_" + d))
    key(sc, pygame.K_RETURN)
    assert sc.keypad == "pass" and sc.join_room == "123456"
    key(sc, pygame.K_KP9), key(sc, pygame.K_9), key(sc, pygame.K_9), key(sc, pygame.K_9)
    key(sc, pygame.K_RETURN)
    reg = sent(t, "register")[0]
    assert reg["room"] == "123456" and reg["pass"] == "9999" and reg["mode"] == "friend"


def test_keypad_ok_ignored_until_complete_and_back_returns_to_name():
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    click(sc, "make")
    click(sc, "k1")
    click(sc, "kok")
    assert sc.keypad == "make" and not sent(t, "register")
    click(sc, "back")
    assert sc.keypad is None and sc.name_field is not None


def test_keypad_paste_on_native(monkeypatch):
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    click(sc, "make")
    monkeypatch.setattr("netgame.webbridge.paste_text", lambda: "pass 12 34 56")
    key(sc, pygame.K_v, mod=pygame.KMOD_CTRL)
    assert sc.digits == "1234"


def test_waiting_room_shows_ids_and_copy(monkeypatch):
    sc, t, a = make()
    idle(sc, t)
    type_text(sc, "Taro")
    click(sc, "make")
    for d in "4321":
        click(sc, "k" + d)
    click(sc, "kok")
    t.recv(t="waiting", room="246810")
    sc.update()
    assert sc.sess.room_id == "246810"
    copied = []
    monkeypatch.setattr("netgame.webbridge.copy_text", lambda s: copied.append(s) or True)
    click(sc, "copy_room")
    click(sc, "copy_key")
    assert copied == ["246810", "4321"]
    assert sc.copied == "key"


# ---------------------------------------------------------------- 準備OK・カウントダウン
def test_match_starts_game_and_ready_flow():
    sc, t, a = make()
    to_ready(sc, t)
    assert sc.phase == "play" and sc.sess.state == "ready"
    assert a.matches == [(77, 0, ["Taro", "Hana"])]
    assert a.bgms[-1] == "game"
    assert sc.chat_flash and sc.chat_sel == 0
    click(sc, "ready")
    assert sent(t, "ready")
    assert "ready" not in sc._pad_rects()                   # 押したら、もう押せない
    assert a.frames == 0


def test_countdown_then_game_runs():
    sc, t, a = make()
    to_ready(sc, t)
    click(sc, "ready")
    t.recv(t="ready_state", seats=[0, 1])
    t.recv(t="start")
    sc.update()
    assert sc.count == sc.COUNTDOWN - 1                # start を受けた、その1フレームから数え始める
    assert sc._view().banner[0] == "5"
    while sc.count > 30:
        sc.update()
    assert a.frames == 0
    assert sc._view().banner[0] == "1"
    for _ in range(32):
        sc.update()
    assert a.frames >= 1
    assert a.controls_log[-1] is True


def test_ready_hint_banner_follows_opponent():
    sc, t, a = make()
    to_ready(sc, t)
    assert sc._view().banner[2] == sc.S["net_ready_hint"]
    t.recv(t="ready_state", seats=[1])
    sc.update()
    assert sc._view().banner[2] == sc.S["net_ready_opp"]
    click(sc, "ready")
    assert sc._view().banner[2] == sc.S["net_ready_wait"]


# ---------------------------------------------------------------- チャット・一時停止
def test_chat_panel_pauses_and_resumes_with_grace():
    sc, t, a = make()
    to_playing(sc, t)
    n = a.frames
    sc.update()
    assert a.frames == n + 1
    click(sc, "chat")
    assert sc.panel
    t.recv(t="paused", seat=0, on=True)
    sc.update()
    assert sent(t, "pause")[-1]["on"] is True
    n = a.frames
    for _ in range(5):
        sc.update()
    assert a.frames == n
    assert sc._view().banner is None or sc._view().banner[0] != "1"
    click(sc, "send")                                  # あいさつを送ると、窓が閉じる
    assert sent(t, "chat")[-1]["text"] == "よろしくお願いします。"
    assert not sc.panel
    sc.update()
    assert sent(t, "pause")[-1]["on"] is False
    t.recv(t="paused", seat=0, on=False)
    sc.update()
    n = a.frames
    for _ in range(sc.GRACE - 5):
        sc.update()
    assert a.frames == n                               # 再開までの間(GRACE フレーム)は進まない
    for _ in range(10):
        sc.update()
    assert a.frames > n


def test_opponent_chat_pauses_without_freezing_my_panel():
    sc, t, a = make()
    to_playing(sc, t)
    t.recv(t="paused", seat=1, on=True)
    sc.update()
    n = a.frames
    sc.update()
    assert a.frames == n
    assert sc._view().banner[0] == sc.S["net_paused"]


def test_chat_template_selection_and_free_text():
    sc, t, a = make()
    to_playing(sc, t)
    click(sc, "chat")
    click(sc, "t3")
    assert sc.chat_sel == 3
    key(sc, pygame.K_RETURN)
    assert sent(t, "chat")[-1]["text"] == "この！！"
    click(sc, "chat")
    click(sc, "tin")
    assert sc.chat_field is not None
    type_text(sc, "gg")
    click(sc, "ok")
    assert sent(t, "chat")[-1]["text"] == "gg"
    assert sc.chat_field is None


def test_chat_input_is_not_passed_to_game_and_escape_cancels():
    sc, t, a = make()
    to_playing(sc, t)
    click(sc, "chat")
    click(sc, "tin")
    before = a.keys
    key(sc, pygame.K_LEFT)
    key(sc, pygame.K_ESCAPE)
    assert a.keys == before
    assert sc.chat_field is None and sc.panel


def test_incoming_chat_flashes_and_sounds():
    sc, t, a = make()
    to_playing(sc, t)
    sc.chat_flash = False
    t.recv(t="chat", seat=1, name="Hana", text="こんにちは")
    sc.update()
    assert sc.chat_flash and "menu_move" in a.sounds
    assert sc._view().last_chat == (False, "Hana", "こんにちは")


def test_pause_released_after_limit():
    sc, t, a = make()
    to_playing(sc, t)
    click(sc, "chat")
    t.recv(t="paused", seat=0, on=True)
    sc.update()
    base = sc.sess.clock()
    sc.sess.clock = lambda: base + PAUSE_MAX + 1       # 止めっぱなし(サーバー側の自動解除より前に、画面が窓を閉じる)
    sc.update()
    assert not sc.panel


# ---------------------------------------------------------------- メニュー(確認)・Esc
def test_menu_confirm_flow():
    sc, t, a = make()
    to_playing(sc, t)
    click(sc, "menu")
    assert sc.confirm
    assert set(sc._pad_rects()) == {"yes", "no"}
    click(sc, "no")
    assert not sc.confirm
    click(sc, "menu")
    assert click(sc, "yes") == "menu"
    assert sent(t, "leave") or sc.sess.state == "closed"


def test_escape_during_play_asks_then_second_escape_cancels():
    sc, t, a = make()
    to_playing(sc, t)
    key(sc, pygame.K_ESCAPE)
    assert sc.confirm
    key(sc, pygame.K_ESCAPE)
    assert not sc.confirm


def test_escape_in_ready_leaves_without_confirm():
    sc, t, a = make()
    to_ready(sc, t)
    assert key(sc, pygame.K_ESCAPE) == "menu"


def test_game_keys_reach_adapter_only_when_playing_and_not_confirming():
    sc, t, a = make()
    to_playing(sc, t)
    key(sc, pygame.K_LEFT)
    assert a.keys == 1
    click(sc, "menu")
    key(sc, pygame.K_LEFT)
    assert a.keys == 1


def test_global_keys_are_taken_by_adapter_first():
    sc, t, a = make()
    idle(sc, t)
    sc.name_field = None                               # 入力中でなければ、M キーは音量へ
    key(sc, pygame.K_m)
    assert a.global_hits == 1


# ---------------------------------------------------------------- 決着・再戦・退出
def finish(sc, t, ranks):
    t.recv(t="result", ranks=ranks, why="normal")
    sc.update()


def test_result_opens_chat_and_selects_greeting():
    sc, t, a = make()
    to_playing(sc, t)
    finish(sc, t, [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}])
    assert sc.sess.state == "over" and sc.panel
    assert sc.chat_sel == 4 and "win" in a.sounds
    assert sc._view().banner[0] == sc.S["win"]
    assert sc._view().banner_top


def test_result_lose_and_after_send_suggests_thanks():
    sc, t, a = make()
    to_playing(sc, t)
    finish(sc, t, [{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}])
    assert sc.chat_sel == 5 and "lose" in a.sounds
    click(sc, "send")
    assert sc.panel                                    # 決着後は窓が開いたまま
    assert sc.chat_sel == 6


def test_rematch_from_panel_and_button():
    sc, t, a = make()
    to_playing(sc, t)
    finish(sc, t, [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}])
    click(sc, "p_retry")
    assert sent(t, "rematch")
    assert "p_retry" not in sc._pad_rects()
    assert sc._view().rematch_wait
    assert sc._view().banner[2] == sc.S["net_wait_rematch"]


def test_new_match_after_rematch_restarts_game():
    sc, t, a = make()
    to_playing(sc, t)
    finish(sc, t, [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}])
    t.recv(t="match", seed=99, you=0, mode="realtime", settings={},
           players=[{"seat": 0, "name": "Taro"}, {"seat": 1, "name": "Hana"}])
    sc.update()
    assert a.matches[-1][0] == 99
    assert not sc.panel and sc.sess.state == "ready"
    assert "ready" in sc._pad_rects()


def test_opponent_left_after_result_shows_only_title_then_auto_exit():
    sc, t, a = make()
    to_playing(sc, t)
    finish(sc, t, [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}])
    t.recv(t="player_left", seat=1)
    sc.update()
    assert not sc.panel
    assert set(sc._pad_rects()) == {"title"}
    assert sc._view().banner[2] == sc.S["net_opp_left"]
    key(sc, pygame.K_t)                                # チャットはもう開けない
    assert not sc.panel
    assert sc._view().leave_left > 0
    clock = [sc.sess.clock()]
    sc.sess.clock = lambda: clock[0] + 10_000
    assert sc.update() == "menu"


def test_title_button_after_result():
    sc, t, a = make()
    to_playing(sc, t)
    finish(sc, t, [{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}])
    click(sc, "close")
    assert click(sc, "title") == "menu"


def test_local_over_banner():
    sc, t, a = make()
    to_playing(sc, t)
    a.over = True
    sc.update()
    assert sc._view().banner[0] == sc.S["game_over"]


def test_disconnect_midgame_goes_to_error():
    sc, t, a = make()
    to_playing(sc, t)
    t.state = "closed"
    sc.update()
    assert sc.phase == "error" and sc.error == "lost"


# ---------------------------------------------------------------- ブラウザの入力欄
def test_web_name_field_is_synced_and_submitted():
    web = FakeWeb()
    sc, t, a = make(web=web, native=False)
    idle(sc, t)
    assert sc.name_field.external
    sc.update()
    assert web.shown and web.shown[2] == 8 and not web.shown[3]
    web.text = "Taro"
    sc.update()
    assert sc.name_field.text == "Taro"
    web.entered = True
    sc.update()
    assert sent(t, "register")[0]["name"] == "Taro"
    sc.update()
    assert web.shown is None                           # 画面が変わったので隠れる


def test_web_name_composing_not_filtered():
    web = FakeWeb()
    sc, t, a = make(web=web, native=False)
    idle(sc, t)
    sc.update()
    web.text, web.composing = "ABCDEFGHIJ", True
    sc.update()
    assert sc.name_field.text == "ABCDEFGH"            # 変換中も最大文字数で切る
    web.composing = False
    sc.update()
    assert sc.name_field.text == "ABCDEFGH" and web.text == "ABCDEFGH"


def test_web_keypad_syncs_digits_both_ways():
    web = FakeWeb()
    sc, t, a = make(web=web, native=False)
    idle(sc, t)
    sc.update()
    web.text = "Taro"
    sc.update()
    click(sc, "make")
    sc.update()
    assert web.shown[3] and web.shown[4]               # 数字用・透明
    web.text = "12ab3456"                              # 貼り付け: 数字だけ・桁数まで
    sc.update()
    assert sc.digits == "1234" and web.text == "1234"
    click(sc, "kdel")
    sc.update()
    assert web.text == "123"
    web.escaped = True
    sc.update()
    assert sc.keypad is None


def test_web_chat_field_only_in_panel():
    web = FakeWeb()
    sc, t, a = make(web=web, native=False)
    to_playing(sc, t)
    sc.update()
    assert web.shown is None
    click(sc, "chat")
    click(sc, "tin")
    sc.update()
    assert web.shown and web.shown[2] == 30
    web.text = "ok!"
    web.entered = True
    sc.update()
    assert sent(t, "chat")[-1]["text"] == "ok!"
    sc.update()
    assert web.shown is None


# ---------------------------------------------------------------- 描画(落ちないこと)
def draw_all(sc, t, screen):
    shots = []

    def shot(name):
        sc.draw(screen)
        shots.append(name)
    shot("connecting")
    hello(sc, t)
    shot("idle")
    type_text(sc, "Taro")
    click(sc, "make")
    shot("keypad")
    for d in "12":
        click(sc, "k" + d)
    shot("keypad-digits")
    click(sc, "back")
    click(sc, "go")
    t.recv(t="waiting")
    sc.update()
    shot("waiting")
    t.recv(t="match", seed=1, you=0, mode="realtime", settings={},
           players=[{"seat": 0, "name": "Taro"}, {"seat": 1, "name": "ハナコ"}])
    sc.update()
    shot("ready")
    click(sc, "ready")
    t.recv(t="ready_state", seats=[0, 1])
    t.recv(t="start")
    sc.update()
    shot("countdown")
    for _ in range(sc.COUNTDOWN + 2):
        sc.update()
    shot("playing")
    click(sc, "chat")
    shot("chat-panel")
    click(sc, "tin")
    shot("chat-typing")
    sc.chat_field = None
    sc.panel = False
    click(sc, "menu")
    shot("confirm")
    click(sc, "no")
    t.recv(t="chat", seat=1, name="ハナコ", text="よろしく！")
    t.recv(t="result", ranks=[{"seat": 0, "rank": 2}, {"seat": 1, "rank": 1}], why="normal")
    sc.update()
    shot("result-panel")
    sc.panel = False
    shot("result")
    t.recv(t="player_left", seat=1)
    sc.update()
    shot("opp-left")
    t.state = "closed"
    sc.update()
    shot("error")
    return shots


@pytest.mark.parametrize("size", [(480, 800), (960, 720), (1024, 900)])
def test_draw_every_screen(size):
    screen = pygame.display.set_mode(size)
    sc, t, a = make(DemoAdapter(size))
    assert len(draw_all(sc, t, screen)) == 15
