from netgame.text import TextField, clean_text, has_glyph, printable


class FakeFont:
    """字形のある文字だけ、大きさのある枠を返す(本物のフォントと同じ: 無い文字も None ではなく大きさ0の枠を返す)。"""
    def __init__(self, glyphs):
        self.glyphs = set(glyphs)

    def metrics(self, ch):
        return [(1, 10, 0, 12, 11)] if ch in self.glyphs else [(0, 0, 0, 0, 7)]


def test_clean_text():
    assert clean_text(" a\nb\x00c ", 10) == "abc"
    assert clean_text("あいう", 2) == "あい"
    assert clean_text("aあ😀", 10, lambda ch: ch < "😀") == "aあ"
    assert clean_text(5, 10) == "" and clean_text(None, 10) == ""
    assert clean_text("a b", 10) == "ab"


def test_textfield():
    f = TextField(3, lambda ch: ch != "x")
    f.insert("あxいうえ")
    assert f.text == "あいう"
    f.backspace()
    assert f.text == "あい" and f.value() == "あい"
    g = TextField(5, text="  ab  ")
    assert g.text == "ab" and not g.external
    h = TextField(3, external=True)
    h.set_compose("あいうえ")
    assert h.external and h.compose == "あいう"


def test_has_glyph_treats_empty_box_as_missing():
    f = FakeFont("あA")
    assert has_glyph(f, "あ") and has_glyph(f, "A")
    assert not has_glyph(f, "漢") and not has_glyph(f, "😀")
    assert has_glyph(f, " ") and has_glyph(f, "　")                    # 空白は、字形がなくてよい
    assert printable(f, "あ漢A😀") == "あ?A?"


def test_has_glyph_survives_a_broken_font():
    class Broken:
        def metrics(self, ch):
            raise RuntimeError("x")
    assert not has_glyph(Broken(), "あ")
