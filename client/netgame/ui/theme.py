"""画面の見た目(色・フォント・背景)。ゲームの雰囲気に合わせて差し替える。"""
import pygame


class Theme:
    bg = (8, 8, 10)
    panel = (22, 22, 26)
    text = (230, 232, 245)
    dim = (150, 158, 200)
    gold = (255, 226, 120)
    red = (255, 120, 130)
    error = (255, 130, 140)                         # つながらない・名前が空などの、エラーの文字
    accent_line = (130, 80, 220)
    me_color = (255, 170, 190)
    opp_color = (150, 195, 255)
    btn_tones = {                                  # (ふだんの色, 影の色)
        "normal": ((62, 70, 118), (28, 30, 56)),
        "accent": ((104, 78, 190), (48, 34, 100)),
        "danger": ((150, 64, 84), (70, 28, 40)),
    }
    btn_depth = 5

    def __init__(self, font=None, background=None, title_color=((255, 226, 120), (110, 40, 190))):
        """font(size) → pygame.font.Font(日本語が出るもの)。background(screen) → 背景を描く。"""
        self._font = font
        self._background = background
        self.title_color = title_color
        self._cache = {}

    def font(self, size):
        size = int(size)
        if self._font is not None:
            return self._font(size)
        if size not in self._cache:
            self._cache[size] = pygame.font.Font(None, size)
        return self._cache[size]

    def background(self, screen):
        if self._background is not None:
            self._background(screen)
        else:
            screen.fill(self.bg)
