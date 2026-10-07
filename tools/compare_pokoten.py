"""M3 の確認用: 画面部品(netgame.ui)の絵を、ポコテン(mesaka/pokoten)の現行の描画とピクセル単位で見比べる。
  python tools/compare_pokoten.py --pokoten ../pokoten [--out /tmp/shots]
始まる前の画面(名前・テンキー・待機・エラー)、チャットの窓、対戦中の右の列のボタンを、同じデータで描いて、違うピクセルの数を出す。
差があれば終了コード 1。--out を付けると、並べた画像(左: ポコテン / 右: netgame)を書き出す。"""
import argparse
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ap = argparse.ArgumentParser()
ap.add_argument("--pokoten", required=True)
ap.add_argument("--out")
args = ap.parse_args()
POKO = os.path.abspath(args.pokoten)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client"))
sys.path.insert(0, POKO)
os.chdir(POKO)

import pygame  # noqa: E402

pygame.init()
screen = pygame.display.set_mode((480, 800))

import ui as pui  # noqa: E402
from strings import S as PS  # noqa: E402
from textutil import font as jp_font  # noqa: E402

from netgame.text import TextField  # noqa: E402
from netgame.ui import screens  # noqa: E402
from netgame.ui.layout import Layout  # noqa: E402
from netgame.ui.strings import Strings  # noqa: E402
from netgame.ui.theme import Theme  # noqa: E402
import netplay  # noqa: E402

theme = Theme(font=jp_font, background=pui.draw_background)
strings = Strings({k: v for k, v in PS.items() if isinstance(v, str)})
UI = screens.Ui(theme, strings, Layout((480, 800)))
pygame.display.set_caption("compare")


def fresh():
    s = pygame.Surface((480, 800))
    s.fill((0, 0, 0))
    return s


def new_pair(**kw):
    """同じデータの、ポコテンの NetView と netgame の View。"""
    a, b = pui.NetView(), screens.View()
    for k, v in kw.items():
        setattr(a, k, v)
        setattr(b, k, v)
    b.settings_label = a.diff_label = kw.get("diff_label", "むずかしさ: ふつう")
    return a, b


def field(text="", ext=False):
    return TextField(8, None, text, external=ext), netplay.TextField(8, None, text, external=ext)


results = []


def check(name, draw_old, draw_new, region=None):
    a, b = fresh(), fresh()
    draw_old(a)
    draw_new(b)
    if region is not None:
        a, b = a.subsurface(region).copy(), b.subsurface(region).copy()
    pa, pb = pygame.image.tobytes(a, "RGB"), pygame.image.tobytes(b, "RGB")
    diff = sum(1 for i in range(0, len(pa), 3) if pa[i:i + 3] != pb[i:i + 3])
    results.append((name, diff))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        both = pygame.Surface((a.get_width() * 2 + 8, a.get_height()))
        both.fill((255, 0, 255))
        both.blit(a, (0, 0))
        both.blit(b, (a.get_width() + 8, 0))
        pygame.image.save(both, os.path.join(args.out, name + ".png"))


pygame.time.get_ticks = lambda: 0                      # 入力欄のカーソルの点滅をそろえる
# ---- 始まる前の画面
for kind, kw in {
    "connecting": {},
    "idle-empty": {},
    "idle-name": {"name": "たろう"},
    "idle-notice": {"notice": "name"},
    "keypad-make": {"keypad": "make", "digits": "12", "keypad_len": 4},
    "keypad-room": {"keypad": "room", "digits": "1234", "keypad_len": 6},
    "keypad-pass": {"keypad": "pass", "digits": "", "keypad_len": 4, "join_room": "123456"},
    "waiting-random": {"name": "たろう", "mode": "random"},
    "waiting-friend": {"name": "たろう", "mode": "friend", "room_id": "246810", "password": "4321", "copied": "room"},
    "error-connect": {"error": "connect"},
    "error-lost": {"error": "lost"},
    "error-detail": {"error": "setup", "error_detail": "RuntimeError: boom"},
}.items():
    a, b = new_pair(**kw)
    k = kind.split("-")[0]
    if k == "keypad":
        k2 = "keypad"
    elif k == "idle":
        k2 = "idle"
    else:
        k2 = k
    if kind == "idle-name":
        pass
    elif kind.startswith("idle"):
        fa, fb = field("", False)
        a.typing, b.typing = fa, fb
    check(kind, lambda s, a=a, k2=k2: pui.draw_net_screen(s, 7, k2, a, pressed=None),
          lambda s, b=b, k2=k2: screens.draw_pre_screen(s, UI, 7, k2, b, pressed=None))
    pressed = {"idle": "go", "keypad": "k5", "waiting": "back", "error": "go", "connecting": "back"}[k2]
    check(kind + "-pressed", lambda s, a=a, k2=k2, p=pressed: pui.draw_net_screen(s, 7, k2, a, pressed=p),
          lambda s, b=b, k2=k2, p=pressed: screens.draw_pre_screen(s, UI, 7, k2, b, pressed=p))

# ---- 入力中の名前
fa, fb = field("たろう")
a, b = new_pair()
a.typing, b.typing = fa, fb
check("idle-typing", lambda s: pui.draw_net_screen(s, 7, "idle", a), lambda s: screens.draw_pre_screen(s, UI, 7, "idle", b))

# ---- チャットの窓
log = [(True, "たろう", "よろしくお願いします。"), (False, "はなこ", "よろしく！"), (False, "はなこ", "せい！！")]
for res in (None, "win"):
    for typing in (False, True):
        a, b = new_pair(chat_log=log, panel=True, chat_sel=3, result=res, can_retry=True, rematch_wait=False)
        if typing:
            fa, fb = field("ありがとう")
            fa.maxlen = fb.maxlen = 30
            a.typing, b.typing = fa, fb
        check("chat-%s-%s" % (res or "play", "typing" if typing else "tiles"),
              lambda s, a=a: pui.draw_chat_panel(s, a, pressed="send"),
              lambda s, b=b: screens.draw_chat_panel(s, UI, b, pressed="send"))

# ---- 対戦中の右の列(ボタン)。盤面などゲーム側の部品は含まず、右の列のボタンの範囲だけ見比べる
REGIONS = {"mid": pygame.Rect(352, 464, 128, 76), "bottom": pygame.Rect(352, 566, 128, 74),
           "left": pygame.Rect(40, 200, 300, 120)}
for name, kw in {
    "col-play": {"chat_flash": False, "last_chat": (False, "はなこ", "よろしく！")},
    "col-result": {"result": "lose", "rematch_wait": False, "chat_enabled": True},
    "col-result-wait": {"result": "win", "rematch_wait": True},
    "col-left": {"result": "win", "opp_left": True, "leave_left": 42, "chat_enabled": False},
}.items():
    a, b = new_pair(**kw)
    a.opp_name = "はなこ"
    a.last_chat = b.last_chat = kw.get("last_chat")
    for pr in (None, "chat"):
        def old(s, a=a, pr=pr):
            g = type("G", (), {"level": 1, "score": 0, "pending_garbage": 0, "queue": [], "state": 0})()
            pui.draw_net_play.__globals__["draw_board"] = lambda *x, **y: None      # 盤面は描かない
            pui.draw_net_play(s, g, [], set(), 7, 30, 30, a, pressed=pr)
        for rn, region in REGIONS.items():
            check("%s-%s-%s" % (name, pr or "idle", rn), old,
                  lambda s, b=b, pr=pr: (theme.background(s), screens.draw_play_overlay(s, UI, 7, b, pressed=pr)),
                  region=region)

# ---- 準備OKボタン・確認ダイアログ
a, b = new_pair(ready_btn="ready")
check("ready-btn", lambda s: pui.draw_button(s, pui.solo_gameover_rects(30, 30)["retry"], PS["net_ready_btn"], False, 24, "accent"),
      lambda s: screens.draw_play_overlay(s, UI, 7, b), region=pygame.Rect(54, 404, 240, 54))
check("confirm", lambda s: pui.draw_confirm(s, 30 + pui.BW // 2, 30 + pui.BH // 2, "yes", PS["net_confirm_sub"]),
      lambda s: screens.draw_post_overlay(s, UI, b, pressed="yes", confirm=True))

bad = 0
for name, diff in results:
    print("%-28s %s" % (name, "同じ" if diff == 0 else "差 %d ピクセル" % diff))
    bad += diff > 0
print("%d 件中 %d 件に差" % (len(results), bad))
sys.exit(1 if bad else 0)
