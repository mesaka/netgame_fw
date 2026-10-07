"""NetGameScene — ネット対戦の画面の流れ全体(接続 → 名前 → 相手さがし/ルーム → 準備OK → カウントダウン → 対戦 → 結果 → 再戦/退出)。
ゲーム側は、GameAdapter を書いて渡すだけ。ポコテンの Net 場面を、ゲームに依存しない形にしたもの。

使い方:
    scene = NetGameScene(MyAdapter())
    # 毎フレーム
    for ev in pygame.event.get(): r = scene.handle(ev)
    r = scene.update()          # r == "menu" なら、タイトルに戻る
    scene.draw(screen)
"""
import math

import pygame

from . import webbridge
from .protocol import COUNTDOWN_SECONDS, MAX_CHAT, MAX_NAME, PASS_LEN, PAUSE_MAX, ROOM_LEN
from .session import NetSession
from .text import TextField, has_glyph
from .transport import make_transport
from .ui.chat import N_TEMPLATES, suggest_template
from .ui.layout import Layout
from .ui.screens import Ui, View, draw_play_overlay, draw_post_overlay, draw_pre_screen
from .ui.strings import Strings
from .ui.theme import Theme
from .ui.widgets import ClickPad

DIGIT_KEYS = {**{getattr(pygame, "K_%d" % d): str(d) for d in range(10)},
              **{getattr(pygame, "K_KP%d" % d): str(d) for d in range(10)}}
KEY_LENS = {"make": PASS_LEN, "room": ROOM_LEN, "pass": PASS_LEN}
ENTER_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER)


class NetGameScene:
    COUNTDOWN = COUNTDOWN_SECONDS * 60      # 全員が準備OKを押したあとのカウントダウン(フレーム)
    GRACE = 60                              # チャットの一時停止が終わってから、再開までの間(フレーム)
    EXIT = "menu"                           # 退出するとき handle/update が返す値

    def __init__(self, adapter, theme=None, strings=None, transport=None, web_input=None, native=None):
        """transport / web_input / native は、テスト用に差し替えられる(既定は、環境に合わせて自動で選ぶ)。"""
        self.adapter = adapter
        self.size = adapter.size
        self.ui = Ui(theme or Theme(), strings if isinstance(strings, Strings) else Strings(strings), Layout(self.size))
        self.S = self.ui.strings
        self.layout = self.ui.layout
        self.pad = ClickPad(lambda n: adapter.sound("menu_ok"))
        self.frame = 0
        self.confirm = False
        self.native = (not webbridge.IS_WEB) if native is None else native
        self._transport = transport
        self.sess = None
        self.name_field = None                  # 名前の入力欄(PCはそのまま打ち込む。ブラウザは入力欄を画面に重ねる)
        self.web = web_input                    # ブラウザ版: 画面に重ねる入力欄(日本語入力・貼り付けが使える)
        if self.web is None and webbridge.IS_WEB:
            try:
                self.web = webbridge.WebInput()
            except Exception as e:              # noqa: BLE001
                print("web input:", repr(e))
        self.web_key = None                     # いま入力欄を重ねている場所("name" / "chat" / "kp-…")
        self.web_text = ""
        self.keypad = None                      # ルームの数字を入れるテンキー: None / "make" / "room" / "pass"
        self.digits = ""
        self.join_room = ""                     # 入るルームのID(テンキーの1つ目の入力)
        self.copied = None
        self.copied_t = 0
        self.chat_field = None
        self.name = adapter.load_name()
        self.match_seen = 0
        self.panel = False
        self.chat_sel = suggest_template("start")
        self.chat_flash = False
        self.local_error = None
        self.error_detail = ""
        self.asked = False
        self.count = self.grace = self.start_seen = 0
        self.was_frozen = self.announced = False
        adapter.bgm("menu")
        self._connect()

    # ---- 接続 ----
    def _connect(self):
        self.local_error = None
        self.error_detail = ""
        self.asked = False
        self.match_seen = 0
        try:
            self.sess = NetSession(self._transport or make_transport(), self.adapter.game_id)
            self.sess.start("")
        except Exception as e:                  # noqa: BLE001
            print("net:", repr(e))
            self.sess = None
            self.local_error = "setup" if webbridge.IS_WEB else "native"
            self.error_detail = "%s: %s" % (type(e).__name__, e)
        if self.native:
            try:
                pygame.key.start_text_input()
            except Exception:                   # noqa: BLE001
                pass
        self.name_field = None
        self.keypad = None

    def _leave(self):
        if self.web is not None:
            try:
                self.web.hide()
            except Exception:                   # noqa: BLE001
                pass
        if self.sess:
            self.sess.close()
        return self.EXIT

    @property
    def phase(self):
        if self.sess is None:
            return "error"
        return {"connecting": "connecting", "idle": "idle", "waiting": "waiting", "ready": "play",
                "playing": "play", "over": "play", "closed": "error"}[self.sess.state]

    @property
    def error(self):
        return self.local_error or (self.sess.error if self.sess else None)

    def _typing(self):
        """いま文字を入力している欄(なければ None)。"""
        if self.phase == "idle":
            return self.name_field
        if self.phase == "play":
            return self.chat_field
        return None

    def _allowed(self, ch):
        return has_glyph(self.ui.theme.font(20), ch)

    # ---- 入力 ----
    def _pad_rects(self):
        L, ph = self.layout, self.phase
        if ph == "play":
            if self.confirm:
                return L.confirm()[1]
            s = self.sess
            if s.state == "over" and s.opp_left:           # 相手が退出した: 「タイトルに戻る」だけ
                return {"title": L.left_title()}
            rects = {"chat": L.chat_button()}
            if s.state == "over":
                if not s.rematch_sent:
                    rects["retry"] = L.result_retry()
                rects["title"] = L.result_title()
            else:
                rects["menu"] = L.menu_button()
            if s.state == "ready" and not s.ready_sent and not self.panel:
                rects["ready"] = L.ready_button()
            if self.panel:
                R = L.chat_panel(s.state == "over")
                rects["close"] = R["close"]
                if s.state == "over":                      # 決着後は、窓の一番下に「もう一度対戦する」「退出する」
                    if not s.rematch_sent:
                        rects["p_retry"] = R["p_retry"]
                    rects["p_leave"] = R["p_leave"]
                if self.chat_field is not None:
                    rects["cancel"], rects["ok"] = R["cancel"], R["ok"]
                else:
                    rects["send"] = R["send"]
                    for i, r in enumerate(R["tiles"]):
                        rects["t%d" % i if i < N_TEMPLATES else "tin"] = r
            return rects
        if ph == "idle":
            if self.keypad:
                return L.keypad()
            return {"field": L.field(), **L.idle_buttons()}
        if ph == "waiting":
            rects = {"back": L.btn_wait()}
            if self.sess.mode == "friend":
                rects["copy_room"], rects["copy_key"] = L.copy_room(), L.copy_key()
            return rects
        if ph == "error":
            return {"go": L.btn_a(), "back": L.btn_b()}
        return {"back": L.btn_b()}

    def handle(self, ev):
        field = self._typing()
        if field is not None and ev.type in (pygame.TEXTINPUT, pygame.TEXTEDITING, pygame.KEYDOWN, pygame.KEYUP):
            return self._handle_text(ev, field)
        if self.adapter.handle_global(ev, "play" if self.phase == "play" else "menu"):
            return None
        if ev.type == pygame.KEYDOWN:
            if self.phase == "idle" and self.keypad:           # テンキー画面: 数字キー・Backspace・Enter・Esc
                self._key_event(ev)
                return None
            if ev.key == pygame.K_ESCAPE:
                if self.phase != "play":
                    return self._leave()
                if self.confirm:
                    self.confirm = False
                elif self.panel:
                    self.panel = False
                elif self.sess.state in ("over", "ready"):
                    return self._leave()
                else:                                          # 対戦中に抜けると負けになるので、確認する
                    self.confirm = True
                    self.adapter.reset_input()
                return None
            if self.phase == "idle" and ev.key in ENTER_KEYS:
                self._submit_name()
            elif self.phase == "play" and not self.confirm:
                if ev.key == pygame.K_t:
                    self._toggle_panel()
                elif ev.key in ENTER_KEYS and self.panel:
                    self._send_selected()
                elif ev.key == pygame.K_r and self.sess.state == "over" and not self.panel:
                    self.sess.rematch()
        self.pad.set_rects(self._pad_rects())
        self.pad.handle(ev)
        if self.phase == "play" and not self.confirm:
            self.adapter.handle(ev)
        return None

    def _handle_text(self, ev, field):
        """文字入力中。キー操作はゲームに渡さない。ブラウザの入力欄(external)は、中身を update で写し取る。"""
        if field.external:
            return None
        if ev.type == pygame.TEXTINPUT:
            field.insert(ev.text)
        elif ev.type == pygame.TEXTEDITING:
            field.set_compose(ev.text)
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                if field.compose:
                    return None
                field.backspace()
            elif ev.key in ENTER_KEYS:
                if field.compose:
                    return None
                if self.phase == "idle":
                    self._submit_name()
                else:
                    self._submit_chat()
            elif ev.key == pygame.K_ESCAPE:
                if self.phase == "idle":
                    return self._leave()
                self.chat_field = None
        return None

    # ---- 名前・ルーム ----
    def _ask_name(self):
        if self.name_field is None:
            self.name_field = TextField(self._name_max(), self._allowed, self.name, external=not self.native)

    def _name_max(self):
        return (self.sess.limits.get("name", MAX_NAME) if self.sess else MAX_NAME)

    def _chat_max(self):
        return (self.sess.limits.get("chat", MAX_CHAT) if self.sess else MAX_CHAT)

    def _commit_name(self):
        """入力中の名前を確定する。名前が空なら入力を促して False。"""
        if self.name_field is not None:
            self.name = self.name_field.value()
        if not self.name:
            self.sess.notice = "name"
            self._ask_name()
            return False
        self.adapter.save_name(self.name)
        self.name_field = None
        return True

    def _submit_name(self, mode="random"):
        if self._commit_name():
            self.sess.register(self.name, mode, self.adapter.settings())

    def _open_keypad(self, mode):
        if self._commit_name():
            self.keypad, self.digits = mode, ""
            self.sess.notice = None
            self.name_field = None
            self.adapter.reset_input()

    def _close_keypad(self):
        self.keypad = None
        self.name_field = None
        self._ask_name()

    def _key_event(self, ev):
        """テンキー画面のキーボード操作。数字は ev.unicode ではなく、キーの種類で見る(ブラウザでは unicode が空のことがある)。"""
        if ev.key == pygame.K_ESCAPE:
            self._close_keypad()
        elif ev.key == pygame.K_BACKSPACE:
            self._key_press("del")
        elif ev.key in ENTER_KEYS:
            self._key_press("ok")
        elif ev.key in DIGIT_KEYS:
            self._key_press(DIGIT_KEYS[ev.key])
        elif ev.key == pygame.K_v and ev.mod & (pygame.KMOD_CTRL | pygame.KMOD_META):
            for ch in "".join(c for c in webbridge.paste_text() if c.isascii() and c.isdigit()):
                self._key_press(ch)

    def _key_press(self, k):
        """make=パスワードを決めてルームを作る / room=入るルームのID / pass=そのルームのパスワード"""
        n = KEY_LENS[self.keypad]
        if k == "del":
            self.digits = self.digits[:-1]
        elif k == "ok":
            if len(self.digits) != n:
                return
            mode, digits = self.keypad, self.digits
            if mode == "room":                         # ルームIDを入れた → 次はパスワード
                self.join_room, self.keypad, self.digits = digits, "pass", ""
                return
            room = self.join_room if mode == "pass" else None
            self.sess.register(self.name, "friend", self.adapter.settings(), password=digits, room=room)
            self.keypad = None
        elif len(self.digits) < n:
            self.digits += k

    def _copy(self, what):
        s = self.sess
        text = {"room": s.room_id, "key": s.password}[what]
        if text and webbridge.copy_text(text):
            self.copied, self.copied_t = what, 120

    # ---- チャット ----
    def _toggle_panel(self):
        if self.sess.state == "over" and self.sess.opp_left:
            return                                     # 相手が退出したので、チャットはできない
        self.panel = not self.panel
        self.chat_field = None
        if self.panel:
            self.chat_flash = False
            self.sess.chat_seen = len(self.sess.chat)
        self.adapter.reset_input()

    def _send_selected(self):
        self._say(self.S["chat_t%d" % self.chat_sel])

    def _say(self, text):
        s = self.sess
        if s.say(text):
            self.chat_flash = False
            self.chat_field = None
            if s.state == "over":                      # 決着後は、お互い退出か再戦を選ぶまで、チャットを続けられる
                self.chat_sel = suggest_template(s.result or "draw", True)
            else:                                      # 対戦中は、送ったら窓を閉じて再開する
                self.panel = False

    def _ask_chat(self):
        """自由入力の欄を出す(窓を開いている間は、お互いのゲームが止まっている)。"""
        self.chat_field = TextField(self._chat_max(), self._allowed, external=not self.native)
        self.adapter.reset_input()

    def _submit_chat(self):
        text = self.chat_field.value()
        self.chat_field = None
        if text:
            self._say(text)

    # ---- ブラウザの入力欄(画面に重ねる) ----
    def _web_want(self):
        """いま入力欄を重ねるべき場所: (キー, Rect, 文字サイズ, 最大文字数, 数字か, 透明か, TextField or None)。要らなければ None。"""
        if self.phase == "idle":
            if self.keypad:                            # テンキー画面: 数字の枠の上に、透明な入力欄を重ねる(貼り付け・キー入力用)
                n = KEY_LENS[self.keypad]
                return ("kp-" + self.keypad, self.layout.keypad_slots(n), 40, n, True, True, None)
            if self.name_field is not None:
                return ("name", self.layout.field(), 24, self.name_field.maxlen, False, False, self.name_field)
        elif self.phase == "play" and self.panel and self.chat_field is not None:
            rect = self.layout.chat_panel(self.sess.state == "over")["input_box"]
            return ("chat", rect, 18, self.chat_field.maxlen, False, False, self.chat_field)
        return None

    def _sync_web(self):
        """ブラウザの入力欄と、ゲーム側の文字(TextField / テンキーの数字)を、毎フレーム同期する。"""
        if self.web is None:
            return None
        want = self._web_want()
        if want is None:
            if self.web_key is not None:
                self.web.hide()
                self.web_key = None
            return None
        key, rect, size, n, digits, invisible, field = want
        if key != self.web_key:
            self.web_text = self.digits if field is None else field.text
            self.web.show(rect, size, n, self.web_text, digits, invisible)
            self.web_key = key
        text, entered, escaped, composing = self.web.poll()
        if field is None:                              # テンキー: 入力欄で打った/貼った数字 → self.digits
            if text != self.web_text:
                new = "".join(c for c in text if c.isascii() and c.isdigit())[:n]
                self.digits = new
                if new != text:
                    self.web.set(new)
                self.web_text = new
            elif self.digits != self.web_text:         # 画面のテンキーを押した → 入力欄へ
                self.web.set(self.digits)
                self.web_text = self.digits
            if entered:
                self._key_press("ok")
            elif escaped:
                self._close_keypad()
            return None
        if not composing:                              # 変換中は触らない(触ると変換が途切れる)
            new = "".join(c for c in text if c >= " " and self._allowed(c))[:n]
            if new != text:
                self.web.set(new)
            field.text = new
        else:
            field.text = text[:n]
        if entered and not composing:
            self._submit_name() if key == "name" else self._submit_chat()
        elif escaped:
            if key == "name":
                self.name_field = None
                return self._leave()
            self.chat_field = None
        return None

    # ---- 毎フレーム ----
    def _start_match(self):
        s = self.sess
        self.match_seen = s.match_no
        self.adapter.start_match(s)
        self.count = 0                                # 準備OKの間は 0。start が届いたらカウントダウン
        self.start_seen = s.start_no
        self.grace = 0
        self.was_frozen = False
        self.announced = False
        self.panel = False
        self.chat_field = None
        self.confirm = False
        self.chat_sel = suggest_template("start")
        self.chat_flash = True                        # 「よろしくお願いします。」を選んであることを、ボタンの点滅で知らせる
        self.adapter.reset_input()
        self.pad.reset()
        self.adapter.bgm("game")

    def update(self):
        self.frame += 1
        self.copied_t = max(0, self.copied_t - 1)
        fired = self.pad.update()
        r = self._on_fired(fired) if fired else None
        if r:
            return r
        s = self.sess
        if s is None:
            return None
        s.update()
        left = s.leave_left()
        if left is not None and left <= 0:             # 相手が退出して一定時間、「タイトルに戻る」が押されなかった
            return self._leave()
        if self.phase == "idle" and not self.asked:
            self.asked = True                          # 名前の入力欄に、そのまま打ち込める
            self._ask_name()
        r = self._sync_web()
        if r:
            return r
        if self.phase == "play":
            if s.match_no != self.match_seen:
                self._start_match()
            self._update_play()
        return None

    def _on_fired(self, f):
        s = self.sess
        if f == "back":
            if self.keypad:
                self._close_keypad()
                return None
            return self._leave()
        if f == "go":
            if self.phase == "error":
                self._connect()
            else:
                self._submit_name()
        elif f == "make":
            self._open_keypad("make")
        elif f == "join":
            self._open_keypad("room")
        elif f == "copy_room":
            self._copy("room")
        elif f == "copy_key":
            self._copy("key")
        elif f in ("kok", "kdel"):
            self._key_press(f[1:])
        elif f[0] == "k" and f[1:].isdigit():
            self._key_press(f[1:])
        elif f == "field":
            self._ask_name()
        elif f == "menu":
            self.confirm = True
            self.adapter.reset_input()
        elif f == "no":
            self.confirm = False
        elif f in ("yes", "title"):
            return self._leave()
        elif f == "chat":
            self._toggle_panel()
        elif f == "close":
            self.panel = False
            self.chat_field = None
        elif f in ("retry", "p_retry"):
            s.rematch()
        elif f == "p_leave":
            return self._leave()
        elif f == "ready":
            s.ready()
            self.panel = False
        elif f == "send":
            self._send_selected()
        elif f == "tin":
            self._ask_chat()
        elif f == "ok":
            self._submit_chat()
        elif f == "cancel":
            self.chat_field = None
        elif f[0] == "t" and f[1:].isdigit():
            self.chat_sel = int(f[1:])
        return None

    def _update_play(self):
        s, a = self.sess, self.adapter
        if self.chat_field is not None or self.confirm:
            a.reset_input()
        if s.unread_chat > 0 and not self.panel:      # 相手のチャットが届いた
            if any(not m[0] for m in s.chat[s.chat_seen:]):
                a.sound("menu_move")
                self.chat_flash = True
            s.chat_seen = len(s.chat)
        elif self.panel:
            s.chat_seen = len(s.chat)
        if s.state == "over" and not self.announced:   # 決着: チャットの窓を開いて、あいさつを選んでおく
            self.announced = True
            a.sound("win" if s.result == "win" else "lose")
            self.chat_sel = suggest_template(s.result or "draw")
            self.chat_flash = True
            self.chat_field = None
            self.panel = not s.opp_left
            self.confirm = False
            a.reset_input()
        if s.state == "over" and s.opp_left and self.panel:
            self.panel, self.chat_field = False, None  # 相手が退出したら、チャットは終わり
        # チャットの入力・選択中は、お互いのゲームを止める(止めっぱなしは PAUSE_MAX 秒で自動的に再開)
        typing = (self.panel or self.chat_field is not None) and s.state == "playing"
        if typing and s.pause_age > PAUSE_MAX:
            self.panel, self.chat_field, typing = False, None, False
        s.set_pause(typing)
        if s.start_no != self.start_seen:              # 全員が準備OK → カウントダウン
            self.start_seen = s.start_no
            self.count = self.COUNTDOWN
        frozen = s.frozen
        if self.was_frozen and not frozen:
            self.grace = self.GRACE
        self.was_frozen = frozen
        if frozen:
            return
        if self.grace > 0:
            self.grace -= 1
            return
        if s.state != "playing":
            return
        if self.count > 0:
            self.count -= 1
            return
        a.update(s, self.chat_field is None and not self.confirm)

    # ---- 描画 ----
    def _view(self):
        s, S, T = self.sess, self.S, self.ui.theme
        v = View()
        v.name = self.name
        v.typing = self.name_field if self.phase == "idle" else None
        v.settings_label = self.adapter.settings_label()
        v.keypad, v.digits = self.keypad, self.digits
        v.keypad_len = KEY_LENS.get(self.keypad, PASS_LEN)
        v.room_id = s.room_id if s else ""
        v.password = s.password if s else ""
        v.join_room = self.join_room
        v.copied = self.copied if self.copied_t > 0 else None
        v.mode = s.mode if s else "random"
        v.notice = s.notice if s else None
        v.error = self.error
        v.error_detail = self.error_detail
        if self.phase != "play":
            return v
        v.result = s.result
        v.ready_btn = None
        if s.state == "ready" and not s.result:
            v.ready_btn = "wait" if s.ready_sent else "ready"
        idle_left = s.idle_left()
        gold, red = T.gold, T.red
        vs = "%s  %s" % (S["net_vs"], s.opp_name)
        if s.result:                                   # 決着(帯は上のほうに出して、チャットの窓と重ならないようにする)
            wait = (S["net_wait_rematch"] if s.rematch_sent else
                    S["net_rematch_req"] if s.opp_wants_rematch else None)
            sub = (S["net_opp_left"] if s.opp_left else
                   S.fmt("net_idle_warn", n=max(0, int(idle_left) + 1)) if idle_left is not None else wait)
            v.banner = (S[s.result], gold if s.result in ("win", "draw") else red, sub)
            v.banner_top = True
        elif s.state == "ready":
            sub = (S["net_ready_wait"] if s.ready_sent else
                   S["net_ready_opp"] if s.opp_ready else S["net_ready_hint"])
            v.banner = (S["net_ready_title"], gold, sub)
        elif self.count > 0 and not s.frozen:
            v.banner = (str((self.count + 59) // 60), gold, vs)
        elif s.paused_opp and not s.paused_me:
            v.banner = (S["net_paused"], gold, S["net_paused_sub"])
        elif self.grace > 0 and not s.frozen:
            v.banner = (S["net_resume"], gold, None)
        elif self.adapter.local_over():
            v.banner = (S["game_over"], red, None)
        v.last_chat = s.chat[-1] if s.chat else None
        v.chat_log = s.chat
        v.chat_flash = self.chat_flash and not self.panel
        v.panel = self.panel
        v.chat_sel = self.chat_sel
        v.typing = self.chat_field
        v.chat_enabled = not s.opp_left or s.state != "over"
        v.can_retry = not s.opp_left
        v.rematch_wait = s.rematch_sent
        v.opp_left = s.opp_left
        lv = s.leave_left()
        v.leave_left = max(0, math.ceil(lv)) if lv is not None else 0
        return v

    def draw(self, screen):
        v = self._view()
        a = self.adapter
        if self.phase != "play":
            kind = {"connecting": "connecting", "idle": "keypad" if self.keypad else "idle",
                    "waiting": "waiting"}.get(self.phase, "error")
            draw_pre_screen(screen, self.ui, self.frame, kind, v, pressed=self.pad.active)
            a.draw_global(screen, "menu")
            return
        a.draw(self.sess, screen, v, self.frame)
        draw_play_overlay(screen, self.ui, self.frame, v, pressed=self.pad.active)
        a.draw_global(screen, "play")
        draw_post_overlay(screen, self.ui, v, pressed=self.pad.active, confirm=self.confirm)
        a.draw_top(screen)
