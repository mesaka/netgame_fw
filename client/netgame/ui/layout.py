"""ボタンや窓の置き場所。基準の画面は 480×800(縦長)で、もっと大きい画面では中央に置く。
ポコテンの画面(480×800)と同じ位置になるよう、座標は基準画面のものをそのまま使っている。"""
import pygame

REF_SIZE = (480, 800)


class Layout:
    def __init__(self, size=REF_SIZE):
        self.size = size
        self.ox = (size[0] - REF_SIZE[0]) // 2
        self.oy = (size[1] - REF_SIZE[1]) // 2

    def R(self, x, y, w, h):
        return pygame.Rect(x + self.ox, y + self.oy, w, h)

    @property
    def center(self):
        return (240 + self.ox, 400 + self.oy)

    # ---- 対戦中(右の列) ----
    @property
    def column_x(self):
        return 352 + self.ox

    column_w = 118

    def chat_button(self):
        return self.R(352, 568, 118, 32)

    def menu_button(self):
        return self.R(352, 606, 118, 30)

    def left_title(self):
        return self.R(54, 214, 276, 54)

    def result_retry(self):
        return self.R(352, 462, 118, 34)

    def result_title(self):
        return self.R(352, 500, 118, 34)

    def ready_button(self):
        return self.R(54, 404, 240, 44)

    def confirm_center(self):
        return (30 + 144 + self.ox, 30 + 288 + self.oy)

    def confirm(self, cx=None, cy=None):
        if cx is None:
            cx, cy = self.confirm_center()
        panel = pygame.Rect(0, 0, 276, 176)
        panel.center = (cx, cy)
        yes = pygame.Rect(panel.x + 16, panel.bottom - 66, 118, 46)
        no = pygame.Rect(panel.right - 16 - 118, panel.bottom - 66, 118, 46)
        return panel, {"yes": yes, "no": no}

    # ---- 始まる前の画面 ----
    def panel(self):
        return self.R(30, 40, 420, 720)

    def title_pos(self):
        return (240 + self.ox, 110 + self.oy)

    def field(self):
        return self.R(60, 400, 360, 52)

    def btn_a(self):
        return self.R(60, 480, 360, 52)

    def btn_b(self):
        return self.R(60, 548, 360, 44)

    def btn_wait(self):
        return self.R(60, 500, 360, 44)

    def copy_room(self):
        return self.R(334, 308, 86, 34)

    def copy_key(self):
        return self.R(334, 380, 86, 34)

    def idle_buttons(self):
        return {"go": self.R(60, 524, 360, 48), "make": self.R(60, 578, 360, 48),
                "join": self.R(60, 632, 360, 48), "back": self.R(60, 692, 360, 40)}

    def keypad(self):
        """k0〜k9 / kdel / kok / back"""
        r = {}
        for i, n in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, "del", 0, "ok"]):
            r["k%s" % n] = self.R(80 + (i % 3) * 110, 380 + (i // 3) * 74, 100, 64)
        r["back"] = self.R(60, 692, 360, 40)
        return r

    def keypad_slots(self, n):
        """数字の枠が並んでいる範囲(ブラウザの入力欄を、ここに透明で重ねる)。"""
        w, gap = (64, 12) if n == 4 else (50, 8)
        x0 = 240 - (n * w + (n - 1) * gap) // 2
        return self.R(x0, 290, n * w + (n - 1) * gap, 72)

    def chat_panel(self, result=False):
        """チャットの窓。テンプレート9個+「文字を入力」=10マス。result=True(決着後)は、一番下に再戦・退出を足す。"""
        panel = self.R(30, 250, 320, 388)
        y0 = 356 if result else 394
        tiles = [self.R(38 + (i % 2) * 156, y0 + (i // 2) * 40, 148, 34) for i in range(10)]
        by = 556 if result else 598
        h = 32 if result else 34
        return {"panel": panel, "close": self.R(350 - 90, 254, 82, 28), "tiles": tiles,
                "send": self.R(38, by, 304, h), "input_box": self.R(38, y0 + 4, 304, 44),
                "cancel": self.R(38, by, 144, h), "ok": self.R(198, by, 144, h),
                "p_retry": self.R(38, 594, 148, 40), "p_leave": self.R(194, 594, 148, 40),
                "log_y": 290 + self.oy}
