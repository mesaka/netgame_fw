"""○×を、本物の Workers ランタイム(wrangler dev)で通して確かめる。2つの NetGameScene を、本物の WebSocket でつなぐ。
  npx wrangler dev -c examples/tictactoe/wrangler.jsonc --port 8787 &
  python examples/tictactoe/e2e.py [ws://localhost:8787/ws]
"""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["NETGAME_SERVER"] = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8787/ws"
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [here, os.path.join(here, "..", "..", "client")]

import pygame  # noqa: E402

pygame.init()
screen = pygame.display.set_mode((480, 800))

from netgame.flow import NetGameScene  # noqa: E402
from ttt_client import BOARD, CELL, TicTacToeAdapter  # noqa: E402

A, B = NetGameScene(TicTacToeAdapter()), NetGameScene(TicTacToeAdapter())


def step(n=1, dt=0.004):
    for _ in range(n):
        for s in (A, B):
            s.update()
            s.draw(screen)
        time.sleep(dt)


def until(cond, limit=3000, what=""):
    for _ in range(limit):
        step()
        if cond():
            return
    raise SystemExit("TIMEOUT %s A=%s B=%s" % (what, A.sess.state, B.sess.state))


def click(sc, cell):
    pos = (BOARD.x + cell % 3 * CELL + CELL // 2, BOARD.y + cell // 3 * CELL + CELL // 2)
    sc.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))


until(lambda: A.phase == "idle" and B.phase == "idle" and A.name_field and B.name_field, what="idle")
A.name_field.text, B.name_field.text = "Taro", "Hana"
A._submit_name()
B._submit_name()
until(lambda: A.sess.state == "ready" and B.sess.state == "ready", what="match")
first, second = (A, B) if A.sess.seat == 0 else (B, A)
print("match ok: 先手 =", first.name)
A.sess.ready()
B.sess.ready()
until(lambda: A.sess.state == "playing" and B.sess.state == "playing" and A.count == 0 and B.count == 0, what="start")
assert first.sess.my_turn and not second.sess.my_turn


def move(sc, other, cell):
    """sc が cell を指して、両方の盤面に反映されるまで待つ。"""
    until(lambda: sc.sess.my_turn, what="turn %d" % cell)
    click(sc, cell)
    until(lambda: sc.adapter.board.cells[cell] is not None and other.adapter.board.cells[cell] is not None, what="move %d" % cell)


click(second, 0)                                   # 手番でない側のクリックは無視される
step(20)
assert second.adapter.board.cells[0] is None
for who, other, cell in [(first, second, 0), (second, first, 3), (first, second, 1), (second, first, 4), (first, second, 2)]:
    move(who, other, cell)
print("moves ok")
assert first.adapter.board.winner() == first.sess.seat
until(lambda: A.sess.state == "over" and B.sess.state == "over", what="result")
print("result:", first.name, first.sess.result, "/", second.name, second.sess.result)
assert (first.sess.result, second.sess.result) == ("win", "lose")
assert A.sess.why == B.sess.why == "normal"
# 再戦 → 盤面が空に戻り、また先手から
A.sess.rematch()
B.sess.rematch()
until(lambda: A.sess.state == "ready" and B.sess.state == "ready", what="rematch")
assert all(c is None for c in A.adapter.board.cells + B.adapter.board.cells)
print("rematch ok")
# 途中退出 → 残った側の勝ち
A.sess.ready()
B.sess.ready()
until(lambda: A.sess.state == "playing" and B.sess.state == "playing" and A.count == 0 and B.count == 0, what="restart")
B._leave()
until(lambda: A.sess.state == "over", what="left")
assert A.sess.result == "win" and A.sess.why == "left"
print("left ok")
A._leave()
print("ALL OK")
