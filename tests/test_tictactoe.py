"""ターン制(TurnAdapter)の見本 ○× のテスト: ルール・手の適用とハッシュ・申告・画面の流れ(偽の通信)。"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from fakes import FakeTransport
from netgame.flow import NetGameScene
from ttt_client import BOARD, CELL, TicTacToeAdapter
from ttt_rules import Board

CONFIG = {"min_players": 2, "max_players": 2, "mode": "turns", "limits": {"name": 8, "chat": 30}}


# ---------------------------------------------------------------- ルール
def play(moves):
    b = Board()
    for seat, cell in moves:
        b.apply(seat, {"cell": cell})
    return b


def test_win_lines_and_ranks():
    b = play([(0, 0), (1, 3), (0, 1), (1, 4), (0, 2)])
    assert b.winner() == 0 and b.line == (0, 1, 2)
    assert b.ranks() == [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}]
    b = play([(0, 0), (1, 2), (0, 1), (1, 4), (0, 8), (1, 6)])
    assert b.ranks() == [{"seat": 1, "rank": 1}, {"seat": 0, "rank": 2}]


def test_draw_gives_both_first_place():
    b = play([(0, 0), (1, 1), (0, 2), (1, 4), (0, 3), (1, 5), (0, 7), (1, 6), (0, 8)])
    assert b.full() and b.winner() is None
    assert b.ranks() == [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 1}]


def test_illegal_moves_are_ignored_the_same_way_for_everyone():
    b = play([(0, 4)])
    for bad in ({"cell": 4}, {"cell": 9}, {"cell": -1}, {"cell": True}, {"cell": "1"}, {}, None, [1]):
        assert b.apply(1, bad) is False
    assert b.apply(2, {"cell": 0}) is False                 # 席が違う
    assert b.serialize() == "....0...."
    b = play([(0, 0), (1, 3), (0, 1), (1, 4), (0, 2)])
    assert b.apply(1, {"cell": 8}) is False                 # 終局後


def test_ongoing_has_no_ranks():
    assert play([(0, 0), (1, 1)]).ranks() is None


# ---------------------------------------------------------------- 画面の流れ(偽の通信)
@pytest.fixture(scope="module", autouse=True)
def _pygame():
    pygame.init()
    pygame.display.set_mode((480, 800))
    yield
    pygame.quit()


def make(seat=0):
    t = FakeTransport()
    t.state, t.opened = "open", True
    a = TicTacToeAdapter()
    sc = NetGameScene(a, transport=t, native=True)
    t.recv(t="hello", id="A", v=1, game="tictactoe", config=CONFIG)
    sc.update()
    for ch in "Taro":
        sc.handle(pygame.event.Event(pygame.TEXTINPUT, text=ch))
    sc.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode=""))
    t.recv(t="match", seed=1, you=seat, mode="turns", settings={},
           players=[{"seat": 0, "name": "Taro" if seat == 0 else "Hana"}, {"seat": 1, "name": "Hana" if seat == 0 else "Taro"}])
    sc.update()
    sc.sess.ready()
    t.recv(t="start", turn={"seat": 0, "seq": 0})
    for _ in range(sc.COUNTDOWN + 3):
        sc.update()
    return sc, t, a


def sent(t, kind):
    return [m for m in t.msgs() if m.get("t") == kind]


def click_cell(sc, cell):
    pos = (BOARD.x + cell % 3 * CELL + CELL // 2, BOARD.y + cell // 3 * CELL + CELL // 2)
    sc.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))


def deliver(sc, t, seat, seq, cell):
    """サーバーが、手と、次の手番を全員へ送る。"""
    t.recv(t="action", seat=seat, seq=seq, d={"cell": cell})
    t.recv(t="turn", seat=1 - seat, seq=seq + 1)
    sc.update()


def test_session_is_available_to_adapter_and_turn_known():
    sc, t, a = make()
    assert a.sess is sc.sess
    assert sc.sess.game_mode == "turns" and sc.sess.my_turn
    assert a.names == ["Taro", "Hana"] and a.me == 0


def test_click_sends_action_only_on_my_turn_and_waits_for_the_server():
    sc, t, a = make(seat=0)
    click_cell(sc, 4)
    assert sent(t, "action")[-1] == {"t": "action", "seq": 0, "d": {"cell": 4}}
    assert a.board.cells[4] is None                         # サーバーから返るまで、盤面は変えない
    deliver(sc, t, 0, 0, 4)
    assert a.board.cells[4] == 0
    n = len(sent(t, "action"))
    click_cell(sc, 0)                                       # 相手の番
    assert len(sent(t, "action")) == n
    click_cell(sc, 4)                                       # 埋まっているマスも送らない
    assert len(sent(t, "action")) == n


def test_each_applied_action_sends_a_hash_and_hashes_match_between_clients():
    sc0, t0, a0 = make(seat=0)
    sc1, t1, a1 = make(seat=1)
    for seq, (seat, cell) in enumerate([(0, 4), (1, 0), (0, 8)]):
        deliver(sc0, t0, seat, seq, cell)
        deliver(sc1, t1, seat, seq, cell)
    h0 = [(m["seq"], m["h"]) for m in sent(t0, "sync")]
    h1 = [(m["seq"], m["h"]) for m in sent(t1, "sync")]
    assert [s for s, _ in h0] == [0, 1, 2] and h0 == h1
    assert len(set(h for _, h in h0)) == 3                  # 手ごとに、状態が変わる


def test_duplicate_action_is_applied_once():
    sc, t, a = make()
    deliver(sc, t, 0, 0, 4)
    t.recv(t="action", seat=0, seq=0, d={"cell": 4})
    sc.update()
    assert a.board.moves == 1 and len(sent(t, "sync")) == 1


def test_winning_move_reports_finish_once_then_result_shows_banner():
    sc, t, a = make(seat=0)
    for seq, (seat, cell) in enumerate([(0, 0), (1, 3), (0, 1), (1, 4), (0, 2)]):
        deliver(sc, t, seat, seq, cell)
    fin = sent(t, "finish")
    assert len(fin) == 1 and fin[0]["ranks"] == [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}]
    assert sc.adapter.local_over()
    sc.update()
    assert len(sent(t, "finish")) == 1
    t.recv(t="result", ranks=fin[0]["ranks"], why="normal")
    sc.update()
    assert sc.sess.result == "win" and sc._view().banner[0] == sc.S["win"]


def test_actions_wait_while_chat_is_open_and_apply_after():
    sc, t, a = make(seat=1)
    sc.panel = True
    sc.update()                                             # 窓を開くと、pause を送る
    assert sent(t, "pause")[-1]["on"] is True
    t.recv(t="paused", seat=1, on=True)                     # サーバーが全員へ返す
    sc.update()
    deliver(sc, t, 0, 0, 4)
    assert a.board.cells[4] is None                         # 止まっている間は適用しない(順番は保つ)
    sc.panel = False
    t.recv(t="paused", seat=1, on=False)
    for _ in range(sc.GRACE + 5):
        sc.update()
    assert a.board.cells[4] == 0


def test_desync_result_explains_itself():
    sc, t, a = make()
    t.recv(t="desync", seq=0)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 1}], why="desync")
    sc.update()
    assert sc.sess.desync_seq == 0
    assert sc._view().banner[2] == sc.S["net_desync"]


@pytest.mark.parametrize("size", [(480, 800), (960, 720)])
def test_draw_states(size):
    screen = pygame.display.set_mode(size)
    sc, t, a = make()
    sc.draw(screen)
    for seq, (seat, cell) in enumerate([(0, 0), (1, 3), (0, 1), (1, 4), (0, 2)]):
        deliver(sc, t, seat, seq, cell)
        sc.draw(screen)
    t.recv(t="result", ranks=[{"seat": 0, "rank": 1}, {"seat": 1, "rank": 2}], why="normal")
    sc.update()
    sc.draw(screen)
