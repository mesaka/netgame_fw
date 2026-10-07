"""画面の部品: ボタン・入力欄・確認ダイアログ・押しボタンの判定(ClickPad)・文字の折り返し。"""
import pygame

from ..text import printable

NO_LINE_START = "、。,.!?)」』"


def wrap(f, text, width):
    """幅 width に収まるように、文字単位で折り返した行のリスト(日本語向け。句読点は行頭に来ない)。"""
    lines, line = [], ""
    for ch in text:
        if line and ch not in NO_LINE_START and f.size(line + ch)[0] > width:
            lines.append(line)
            line = ""
        line += ch
    if line:
        lines.append(line)
    return lines


def fit(img, max_w):
    """画像を、幅 max_w に収まるように縮める(収まっていれば、そのまま)。"""
    if img.get_width() <= max_w:
        return img
    h = max(1, int(img.get_height() * max_w / img.get_width()))
    return pygame.transform.smoothscale(img, (max_w, h))


def outlined(f, text, fill, stroke, r=2):
    body = f.render(text, True, fill)
    edge = f.render(text, True, stroke)
    surf = pygame.Surface((body.get_width() + 2 * r, body.get_height() + 2 * r), pygame.SRCALPHA)
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if (dx or dy) and dx * dx + dy * dy <= r * r + 1:
                surf.blit(edge, (r + dx, r + dy))
    surf.blit(body, (r, r))
    return surf


def draw_button(screen, theme, rect, label, pressed=False, size=22, tone="normal"):
    """立体的なボタン。押している間は、下に沈んで、明るくなり、金色の縁がつく。"""
    face, shade = theme.btn_tones[tone]
    radius = min(14, rect.height // 3)
    if pressed:
        face = tuple(min(255, int(c * 1.45) + 25) for c in face)
        r = rect.move(0, theme.btn_depth - 1)
        pygame.draw.rect(screen, face, r, border_radius=radius)
        pygame.draw.rect(screen, theme.gold, r, width=3, border_radius=radius)
    else:
        r = rect
        pygame.draw.rect(screen, shade, rect.move(0, theme.btn_depth), border_radius=radius)
        pygame.draw.rect(screen, face, rect, border_radius=radius)
        pygame.draw.rect(screen, tuple(min(255, c + 40) for c in face), rect, width=2, border_radius=radius)
    img = theme.font(size).render(label, True, (255, 255, 255) if pressed else theme.text)
    screen.blit(img, img.get_rect(center=r.center))


def draw_field(screen, theme, rect, field, size=20, placeholder=None, ticks=0):
    """入力欄。field は TextField(なければ None)。external(ブラウザの入力欄が重なる)なら、枠だけ描く。"""
    pygame.draw.rect(screen, (10, 10, 22), rect, border_radius=10)
    pygame.draw.rect(screen, theme.gold if field is not None and field.active else (90, 70, 150), rect, width=2,
                     border_radius=10)
    f = theme.font(size)
    text = field.text if field else ""
    comp = field.compose if field else ""
    if not text and not comp and placeholder:
        img = f.render(placeholder, True, (110, 114, 140))
        screen.blit(img, img.get_rect(midleft=(rect.x + 12, rect.centery)))
        return
    if field is not None and field.external:
        return
    img = f.render(printable(f, text), True, theme.text)
    x = rect.x + 12
    screen.blit(img, img.get_rect(midleft=(x, rect.centery)))
    x += img.get_width()
    if comp:                                              # 変換中の文字(下線つき)
        ci = f.render(printable(f, comp), True, theme.gold)
        screen.blit(ci, ci.get_rect(midleft=(x, rect.centery)))
        pygame.draw.line(screen, theme.gold, (x, rect.centery + size // 2 + 2), (x + ci.get_width(), rect.centery + size // 2 + 2))
        x += ci.get_width()
    if field is not None and field.active and (ticks // 500) % 2 == 0:
        pygame.draw.line(screen, theme.text, (x + 2, rect.centery - size // 2), (x + 2, rect.centery + size // 2), 2)


def draw_confirm(screen, theme, strings, layout, pressed=None, sub=None, center=None):
    dim = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 170))
    screen.blit(dim, (0, 0))
    cx, cy = center or layout.confirm_center()
    panel, btns = layout.confirm(cx, cy)
    pygame.draw.rect(screen, (22, 22, 42), panel, border_radius=18)
    pygame.draw.rect(screen, (130, 80, 220), panel, width=3, border_radius=18)
    t = theme.font(22).render(strings["confirm_title"], True, theme.gold)
    screen.blit(t, t.get_rect(center=(panel.centerx, panel.y + 34)))
    t2 = theme.font(15).render(sub or strings["confirm_sub"], True, theme.dim)
    screen.blit(t2, t2.get_rect(center=(panel.centerx, panel.y + 66)))
    draw_button(screen, theme, btns["yes"], strings["confirm_yes"], pressed == "yes", 20, "danger")
    draw_button(screen, theme, btns["no"], strings["confirm_no"], pressed == "no", 20, "accent")


class ClickPad:
    """画面上の押しボタン。押している間は active にその名前が入り、ボタンの上で離すと、少し(PRESS_FRAMES)光ってから
    update() がその名前を返す。on_press は、確定したときに鳴らす音など(省略可)。"""
    PRESS_FRAMES = 7

    def __init__(self, on_fire=None):
        self.rects = {}
        self.down = None
        self.pos = (0, 0)
        self.fired = None                   # (名前, 残りフレーム)
        self.on_fire = on_fire

    def set_rects(self, rects):
        self.rects = rects
        if self.down not in rects:
            self.down = None

    def handle(self, ev):
        if self.fired:
            return
        if ev.type == pygame.MOUSEMOTION:
            self.pos = ev.pos
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.pos = ev.pos
            self.down = next((n for n, r in self.rects.items() if r.collidepoint(ev.pos)), None)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            n, self.down = self.down, None
            if n in self.rects and self.rects[n].collidepoint(ev.pos):
                self.fired = (n, self.PRESS_FRAMES)
                if self.on_fire:
                    self.on_fire(n)

    @property
    def active(self):
        if self.fired:
            return self.fired[0]
        if self.down in self.rects and self.rects[self.down].collidepoint(self.pos):
            return self.down
        return None

    def update(self):
        if not self.fired:
            return None
        name, n = self.fired
        if n > 1:
            self.fired = (name, n - 1)
            return None
        self.fired = None
        return name

    def reset(self):
        self.down = None
        self.fired = None
