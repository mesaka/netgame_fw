"""取り込み・フォントの道具と、雛形(templates/)のテスト。"""
import glob
import importlib.util
import os
import shutil
import subprocess
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from fakes import FakeTransport

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 取り込み(copy_to_game.sh)
@pytest.mark.skipif(shutil.which("bash") is None, reason="bash がない")
def test_copy_to_game(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    (game / "netgame").mkdir()
    (game / "netgame" / "old.py").write_text("x")             # 古いコピーは消える
    out = subprocess.run(["bash", os.path.join(ROOT, "tools", "copy_to_game.sh"), str(game)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    for f in ["netgame/__init__.py", "netgame/flow.py", "netgame/adapter.py", "netgame/ui/screens.py", "netgame/strings_ja.py",
              "netgame/LICENSE", "netgame/NOTICE", "netgame/SOURCE_COMMIT",
              "server/netgame/core.js", "server/netgame/worker.js", "server/netgame/text.js", "server/netgame/testkit.js"]:
        assert (game / f).is_file(), f
    assert not (game / "netgame" / "old.py").exists()
    assert not list((game / "netgame").rglob("__pycache__"))
    # コピーした netgame が、そのまま import できる(pygame を使う部分は、ui / flow だけ)
    r = subprocess.run([sys.executable, "-c", "import netgame, netgame.session; import sys; assert 'pygame' not in sys.modules"],
                       cwd=game, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- フォント(build_font.py)
def test_collect_chars_includes_netgame_strings_input_chars_and_game_strings(tmp_path):
    bf = load("tools/build_font.py", "build_font")
    strings = tmp_path / "game_strings.py"
    strings.write_text('S = {"title": "龍のゲーム", "n": 3}\n', encoding="utf-8")
    chars = bf.collect_chars([str(strings) + ":S"], ["♪"])
    for ch in "龍のゲーム♪Aあア！":                              # ゲームの文言・追加の文字・名前に入力できる文字
        assert ch in chars, ch
    for ch in "ネット対戦":                                     # netgame の既定の文言
        assert ch in chars
    assert "3" in chars and chars == "".join(sorted(set(chars)))
    assert "ぬ" not in bf.collect_chars([], [], input_chars=False)     # 入力用の文字は、外せる
    assert "ぬ" in chars


def test_build_font_makes_a_smaller_font(tmp_path):
    pytest.importorskip("fontTools")
    fonts = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    if not fonts:
        pytest.skip("元にするフォントがない")
    out = tmp_path / "sub.ttf"
    bf = load("tools/build_font.py", "build_font2")
    bf.main(["--font", fonts[0], "--out", str(out), "--text", "AB"])
    assert out.is_file() and out.stat().st_size < os.path.getsize(fonts[0])


# ---------------------------------------------------------------- 雛形(templates/client/adapter.py)
def test_client_template_runs_through_the_scene():
    pygame.init()
    screen = pygame.display.set_mode((480, 800))
    from netgame.flow import NetGameScene
    mod = load("templates/client/adapter.py", "tpl_adapter")
    t = FakeTransport()
    t.state, t.opened = "open", True
    a = mod.MyGameAdapter()
    sc = NetGameScene(a, transport=t, native=True)
    t.recv(t="hello", id="A", v=1, game="mygame", config={"limits": {"name": 8, "chat": 30}})
    sc.update()
    for ch in "Taro":
        sc.handle(pygame.event.Event(pygame.TEXTINPUT, text=ch))
    sc.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0, unicode=""))
    assert t.msgs()[-1]["settings"] == {"level": "normal"}
    t.recv(t="match", seed=1, you=0, mode="realtime", settings={"level": "normal"},
           players=[{"seat": 0, "name": "Taro"}, {"seat": 1, "name": "Hana"}])
    sc.update()
    sc.sess.ready()
    t.recv(t="start")
    for _ in range(sc.COUNTDOWN + 3):
        sc.update()
        sc.draw(screen)
    t.recv(t="event", seat=1, k="move", d={"x": 7})
    sc.update()
    assert a.opp == 7
    assert any(m.get("k") == "move" for m in t.msgs())
    pygame.quit()
