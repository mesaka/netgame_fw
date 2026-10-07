"""対戦が始まる前の画面と、対戦中に重ねる部品(右の列のボタン・チャットの窓・帯)の描画。
状態(通信・入力)は持たず、View というデータだけを受け取って描く。"""
from collections import namedtuple

import pygame

from ..text import printable
from .chat import N_TEMPLATES
from .widgets import draw_button, draw_confirm, draw_field, fit, outlined, wrap

Ui = namedtuple("Ui", "theme strings layout")


class View:
    """描画用のデータ。"""
    name = ""
    settings_label = ""
    error = None                 # None / "connect" / "lost" / "timeout" / "setup" / "native" / "game" / "version"
    error_detail = ""
    notice = None                # 名前・ルームのやり直しの理由("name" / "key" / "room" / "pass")
    typing = None                # 入力中の TextField
    mode = "random"
    room_id = ""
    password = ""
    keypad = None                # None / "make" / "room" / "pass"
    keypad_len = 4
    digits = ""
    join_room = ""
    copied = None                # "room" / "key"
    # 対戦中
    result = None                # None / "win" / "lose" / "draw"
    banner = None                # (大きい字, 色, 小さい字)
    banner_top = False
    ready_btn = None             # None / "ready" / "wait"
    last_chat = None
    chat_log = ()
    chat_flash = False
    chat_enabled = True
    panel = False
    chat_sel = 0
    can_retry = True
    rematch_wait = False
    opp_left = False
    leave_left = 0


def draw_wrapped_center(screen, ui, text, cx, y, size, color, max_w, lines=3):
    f = ui.theme.font(size)
    for i, ln in enumerate(wrap(f, text, max_w)[:lines]):
        img = f.render(ln, True, color)
        screen.blit(img, img.get_rect(center=(cx, y + i * (size + 4))))


# ------------------------------------------------------------ 始まる前
def draw_pre_screen(screen, ui, frame, kind, v, pressed=None):
    """kind: connecting / idle(名前の入力・相手の決め方) / keypad(ルームの数字) / waiting / error"""
    T, S, L = ui.theme, ui.strings, ui.layout
    T.background(screen)
    panel = pygame.Surface(L.panel().size, pygame.SRCALPHA)
    pygame.draw.rect(panel, (0, 0, 0, 165), panel.get_rect(), border_radius=22)
    pygame.draw.rect(panel, T.accent_line + (200,), panel.get_rect(), width=3, border_radius=22)
    screen.blit(panel, L.panel())
    t = outlined(T.font(44), S["net_title"], T.title_color[0], T.title_color[1], 3)
    screen.blit(t, t.get_rect(center=L.title_pos()))
    dots = "." * (1 + (frame // 20) % 3)
    cx, oy = 240 + L.ox, L.oy

    def center(text, y, size=20, color=T.text):
        img = fit(T.font(size).render(text, True, color), 380)
        screen.blit(img, img.get_rect(center=(cx, y + oy)))

    def btn(rect, label, name, size, tone="normal", on=False):
        draw_button(screen, T, rect, label, pressed == name or on, size, tone)

    ticks = pygame.time.get_ticks()
    if kind == "connecting":
        center(S["net_connecting"] + dots, 330, 22)
        btn(L.btn_b(), S["net_back"], "back", 20)
    elif kind == "idle":
        B = L.idle_buttons()
        field = L.field()
        center(S["net_idle_guide"], 220, 17)
        if v.notice:
            center(S["net_err_" + v.notice], 350, 15, T.error)
        center(S["net_name_label"], 376, 18, T.dim)
        shown_name = v.typing is None and v.name
        draw_field(screen, T, field, v.typing, 24, None if shown_name else
                   (S["net_name_tap"] if v.typing is None else S["net_name_type"]), ticks)
        if shown_name:
            f = T.font(24)
            img = f.render(printable(f, v.name), True, T.text)
            screen.blit(img, img.get_rect(midleft=(field.x + 12, field.centery)))
        center(S["net_chars"], 470, 14, T.dim)
        center(v.settings_label, 498, 16, T.dim)
        btn(B["go"], S["net_find"], "go", 20, "accent")
        btn(B["make"], S["net_mode_make"], "make", 20)
        btn(B["join"], S["net_mode_join"], "join", 20)
        btn(B["back"], S["net_back"], "back", 18)
    elif kind == "keypad":
        center(S["net_key_" + v.keypad], 200, 21, T.gold)
        center(S["net_key_sub_" + v.keypad], 234, 15, T.dim)
        if v.keypad == "pass":
            center("%s %s" % (S["net_room_id"], v.join_room), 262, 16)
        n = v.keypad_len
        w, gap = (64, 12) if n == 4 else (50, 8)
        slots = L.keypad_slots(n)
        center(S["net_key_kbd"], 372, 12, T.dim)
        for i in range(n):                                    # 数字の枠
            r = pygame.Rect(slots.x + i * (w + gap), slots.y, w, 72)
            pygame.draw.rect(screen, (10, 10, 22), r, border_radius=12)
            pygame.draw.rect(screen, T.gold if i == len(v.digits) else (90, 70, 150), r, width=2, border_radius=12)
            if i < len(v.digits):
                d = T.font(40 if n == 4 else 34).render(v.digits[i], True, T.text)
                screen.blit(d, d.get_rect(center=r.center))
        for name, r in L.keypad().items():
            if name == "back":
                btn(r, S["net_cancel"], name, 18)
            elif name == "kdel":
                btn(r, S["net_key_del"], name, 20, "danger")
            elif name == "kok":
                btn(r, S["net_key_ok"], name, 20, "accent")
            else:
                btn(r, name[1:], name, 30)
    elif kind == "waiting":
        friend = v.mode == "friend"
        center("%s: %s" % (S["net_name_label"], v.name), 232 if friend else 250, 18)
        center(v.settings_label, 260 if friend else 282, 16, T.dim)
        if friend:
            center(S["net_room_id"], 290, 16, T.dim)
            center(v.room_id or "…", 326, 40, T.gold)
            btn(L.copy_room(), S["net_copied"] if v.copied == "room" else S["net_copy"], "copy_room", 12,
                on=v.copied == "room")
            center(S["net_room_pass"], 362, 16, T.dim)
            center(" ".join(v.password), 398, 40, T.gold)
            btn(L.copy_key(), S["net_copied"] if v.copied == "key" else S["net_copy"], "copy_key", 12,
                on=v.copied == "key")
            center(S["net_room_waiting"] + dots, 444, 22, T.gold)
            center(S["net_room_sub"], 474, 14)
        else:
            center(S["net_waiting"] + dots, 350, 24, T.gold)
            center(S["net_waiting_sub"], 390, 14, T.dim)
        btn(L.btn_wait(), S["net_cancel"], "back", 20)
    else:
        main, sub = {"lost": ("net_err_lost", "net_err_lost_sub"),
                     "timeout": ("net_err_timeout", "net_err_timeout_sub"),
                     "setup": ("net_err_setup", "net_err_setup_sub"),
                     "native": ("net_err_native", "net_err_native_sub")}.get(
            v.error, ("net_err_connect", "net_err_connect_sub"))
        center(S[main], 330, 24, T.error)
        center(S[sub], 372, 15, T.dim)
        if v.error_detail:
            for i, ln in enumerate(wrap(T.font(12), v.error_detail, 380)[:3]):
                center(ln, 410 + i * 18, 12, (120, 124, 150))
        btn(L.btn_a(), S["net_retry"], "go", 22, "accent")
        btn(L.btn_b(), S["net_back"], "back", 20)


# ------------------------------------------------------------ 対戦中に重ねる部品
def draw_play_overlay(screen, ui, frame, v, pressed=None, confirm=False, confirm_sub=None):
    """右の列のボタン(チャット・メニュー・結果)・最後のチャット・準備OK・チャットの窓・確認ダイアログ。
    盤面と、ゲーム独自の部品は、アダプターが先に描いておく。"""
    T, S, L = ui.theme, ui.strings, ui.layout
    px, pw = L.column_x, L.column_w
    if v.last_chat and not v.result:                      # 最後のチャット(決着後は、その場所に「もう一度」を出す)
        mine, _, text = v.last_chat
        box = pygame.Rect(px, 464 + L.oy, pw, 70)
        pygame.draw.rect(screen, (30, 32, 56), box, border_radius=8)
        pygame.draw.rect(screen, T.me_color if mine else (110, 170, 255), (box.x, box.y + 4, 4, box.h - 8),
                         border_radius=2)
        f = T.font(13)
        for i, line in enumerate(wrap(f, printable(f, text), pw - 18)[:4]):
            screen.blit(f.render(line, True, T.text), (box.x + 10, box.y + 5 + i * 16))
    if v.result and v.opp_left:                           # 相手が退出した: 大きな「タイトルに戻る」。押されなくても自動で戻る
        r = L.left_title()
        draw_button(screen, T, r, S["net_back_title"], pressed == "title", 24, "accent")
        t = T.font(14).render(S.fmt("net_leave_auto", n=max(0, v.leave_left)), True, T.text)
        tr = t.get_rect(center=(r.centerx, r.bottom + 22))
        back = pygame.Surface((tr.w + 20, tr.h + 8), pygame.SRCALPHA)
        pygame.draw.rect(back, (0, 0, 0, 190), back.get_rect(), border_radius=8)
        screen.blit(back, back.get_rect(center=tr.center))
        screen.blit(t, tr)
    elif v.result:
        draw_button(screen, T, L.result_retry(), S["net_wait_short"] if v.rematch_wait else S["btn_retry"],
                    pressed == "retry" or v.rematch_wait, 15, "accent")
        draw_button(screen, T, L.result_title(), S["chat_leave"], pressed == "title", 15, "danger")
    else:
        draw_button(screen, T, L.menu_button(), S["menu_btn"], pressed == "menu", 15)
    if v.ready_btn:
        draw_button(screen, T, L.ready_button(), S["net_ready_btn"], pressed == "ready" or v.ready_btn == "wait",
                    24, "accent")
    if v.chat_enabled:
        glow = v.chat_flash and (frame // 15) % 2 == 0
        draw_button(screen, T, L.chat_button(), S["chat_btn"], pressed == "chat" or glow, 16, "accent")


def draw_post_overlay(screen, ui, v, pressed=None, confirm=False, confirm_sub=None, confirm_center=None):
    """チャットの窓と確認ダイアログ(いちばん手前)。"""
    if v.panel:
        draw_chat_panel(screen, ui, v, pressed)
    if confirm:
        draw_confirm(screen, ui.theme, ui.strings, ui.layout, pressed, confirm_sub or ui.strings["net_confirm_sub"],
                     confirm_center)


def draw_chat_panel(screen, ui, v, pressed=None):
    T, S, L = ui.theme, ui.strings, ui.layout
    res = bool(v.result)
    R = L.chat_panel(res)
    panel = R["panel"]
    bg = pygame.Surface(panel.size, pygame.SRCALPHA)
    pygame.draw.rect(bg, (14, 14, 30, 238), bg.get_rect(), border_radius=16)
    screen.blit(bg, panel)
    pygame.draw.rect(screen, T.accent_line, panel, width=3, border_radius=16)
    screen.blit(T.font(20).render(S["chat_title"], True, T.gold), (panel.x + 14, panel.y + 8))
    draw_button(screen, T, R["close"], S["chat_close"], pressed == "close", 15)

    f = T.font(14)                                         # ログ(新しいものを下に。入りきらない古いものは出さない)
    blocks = []
    for mine, name, text in v.chat_log:
        tag = S["net_you"] if mine else (name or S["net_opp"])
        color = T.me_color if mine else T.opp_color
        blocks.append([(ln, color) for ln in wrap(f, printable(f, "%s: %s" % (tag, text)), panel.w - 28)])
    flat = []
    for blk in reversed(blocks):
        if len(flat) + len(blk) > (3 if res else 5):
            break
        flat = blk + flat
    if not flat:
        flat = [(S["chat_empty"], T.dim)]
    for i, (ln, color) in enumerate(flat):
        screen.blit(f.render(ln, True, color), (panel.x + 14, R["log_y"] + i * 19))

    if v.typing is not None:
        t = T.font(15).render(S.fmt("chat_prompt", n=v.typing.maxlen), True, T.dim)
        screen.blit(t, (R["input_box"].x, R["input_box"].y - 22))
        draw_field(screen, T, R["input_box"], v.typing, 18, None, pygame.time.get_ticks())
        cnt = T.font(14).render("%d/%d" % (len(v.typing.text), v.typing.maxlen), True, T.dim)
        screen.blit(cnt, cnt.get_rect(topright=(R["input_box"].right, R["input_box"].bottom + 4)))
        screen.blit(T.font(14).render(S["chat_type_hint"], True, T.dim), (R["input_box"].x, R["input_box"].bottom + 4))
        draw_button(screen, T, R["cancel"], S["chat_cancel"], pressed == "cancel", 16)
        draw_button(screen, T, R["ok"], S["chat_send"], pressed == "ok", 16, "accent")
    else:
        for i, r in enumerate(R["tiles"]):
            if i < N_TEMPLATES:
                on, label = i == v.chat_sel, S["chat_t%d" % i]
            else:
                on, label = False, S["chat_input"]
            pygame.draw.rect(screen, (95, 70, 170) if on else (42, 46, 74), r, border_radius=10)
            if on:
                pygame.draw.rect(screen, T.gold, r, width=3, border_radius=10)
            img = fit(T.font(15).render(label, True, T.text), r.w - 10)
            screen.blit(img, img.get_rect(center=r.center))
        draw_button(screen, T, R["send"], S["chat_send"], pressed == "send", 18, "accent")
    if res:                                                # 決着後: お互いが再戦か退出を選ぶまで、チャットは続けられる
        if v.can_retry:
            draw_button(screen, T, R["p_retry"], S["chat_rematch_wait"] if v.rematch_wait else S["chat_rematch"],
                        pressed == "p_retry" or v.rematch_wait, 15 if v.rematch_wait else 17, "accent")
        draw_button(screen, T, R["p_leave"], S["chat_leave"], pressed == "p_leave", 17, "danger")
