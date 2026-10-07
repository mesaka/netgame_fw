"""○×のクライアント側アダプター(TurnAdapter の見本)。盤面をクリックして手を指す。
日本語を出すには、font(size) → pygame.font.Font を渡す(省略すると、英字の標準フォント)。"""
import pygame

from netgame.adapter import TurnAdapter
from ttt_rules import Board

BOARD = pygame.Rect(36, 200, 300, 300)       # 右の列(x=352〜)のボタンと重ならない位置
CELL = BOARD.w // 3


class TicTacToeAdapter(TurnAdapter):
    game_id = "tictactoe"
    size = (480, 800)

    def __init__(self, font=None):
        super().__init__()
        self._font = font
        self.board = Board()
        self.me = 0
        self.names = ["", ""]
        self.hover = None

    def font(self, size):
        return self._font(size) if self._font else pygame.font.Font(None, size)

    # ---- ルール(TurnAdapter) ----
    def on_match(self, sess):
        self.board = Board()
        self.me = sess.seat
        self.names = [p["name"] for p in sorted(sess.players, key=lambda p: p["seat"])]

    def on_action(self, seat, seq, action):
        self.board.apply(seat, action)

    def state_hash(self):
        return self.digest(self.board.serialize())

    def is_finished(self):
        return self.board.ranks()

    # ---- 入力 ----
    def cell_at(self, pos):
        if not BOARD.collidepoint(pos):
            return None
        return (pos[1] - BOARD.y) // CELL * 3 + (pos[0] - BOARD.x) // CELL

    def handle(self, ev):
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.cell_at(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            cell = self.cell_at(ev.pos)
            if cell is not None and self.sess is not None and self.board.cells[cell] is None:
                self.play(self.sess, {"cell": cell})

    # ---- 描画 ----
    def draw(self, sess, screen, view, frame):
        screen.fill((14, 14, 28))
        f, big = self.font(26), self.font(60)
        for i, n in enumerate(self.names):                   # 名前と、その人の印(○ / ×)
            turn = sess.turn and sess.turn["seat"] == i and sess.state == "playing"
            img = f.render(n, True, (255, 226, 120) if turn else (150, 158, 200))
            r = img.get_rect(center=(200, 40 + i * 36))
            screen.blit(img, r)
            c = (r.x - 24, r.centery)
            if i == 0:
                pygame.draw.circle(screen, (228, 76, 88), c, 11, 4)
            else:
                pygame.draw.line(screen, (78, 132, 236), (c[0] - 10, c[1] - 10), (c[0] + 10, c[1] + 10), 4)
                pygame.draw.line(screen, (78, 132, 236), (c[0] + 10, c[1] - 10), (c[0] - 10, c[1] + 10), 4)
        for i in range(4):
            pygame.draw.line(screen, (90, 70, 150), (BOARD.x + i * CELL, BOARD.y), (BOARD.x + i * CELL, BOARD.bottom), 4)
            pygame.draw.line(screen, (90, 70, 150), (BOARD.x, BOARD.y + i * CELL), (BOARD.right, BOARD.y + i * CELL), 4)
        line = self.board.line if self.board.winner() is not None else ()
        for i, c in enumerate(self.board.cells):
            r = pygame.Rect(BOARD.x + i % 3 * CELL, BOARD.y + i // 3 * CELL, CELL, CELL)
            if i in line:
                pygame.draw.rect(screen, (60, 50, 20), r.inflate(-8, -8))
            elif c is None and self.hover == i and sess.my_turn:
                pygame.draw.rect(screen, (30, 30, 58), r.inflate(-8, -8))
            if c == 0:
                pygame.draw.circle(screen, (228, 76, 88), r.center, CELL // 2 - 16, 8)
            elif c == 1:
                m = 18
                pygame.draw.line(screen, (78, 132, 236), (r.x + m, r.y + m), (r.right - m, r.bottom - m), 10)
                pygame.draw.line(screen, (78, 132, 236), (r.right - m, r.y + m), (r.x + m, r.bottom - m), 10)
        if sess.state == "playing" and sess.turn and not view.banner:
            msg = "あなたの番です" if sess.my_turn else "相手の番です"
            img = f.render(msg, True, (255, 226, 120) if sess.my_turn else (150, 158, 200))
            screen.blit(img, img.get_rect(center=(186, 540)))
        if view.banner:
            text, color, sub = view.banner
            img = big.render(text, True, color)
            screen.blit(img, img.get_rect(center=(190, 125 if view.banner_top else 350)))
            if sub:
                s = f.render(sub, True, (230, 232, 245))
                screen.blit(s, s.get_rect(center=(190, 168 if view.banner_top else 400)))
