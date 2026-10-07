"""文字入力まわり(pygame非依存): 文字の整形・入力欄(TextField)・字形の判定。"""
from __future__ import annotations


def clean_text(s, maxlen, allowed=None) -> str:
    """制御文字と改行を除き、前後の空白を削って maxlen 文字に切る。allowed(ch) が False の文字も除く。"""
    if not isinstance(s, str):
        return ""
    out = "".join(ch for ch in s if ch >= " " and ch != "\x7f" and not ("\x80" <= ch <= "\x9f")
                  and ch not in "  " and (allowed is None or allowed(ch)))
    return out.strip()[:maxlen]


class TextField:
    """文字入力欄。text が確定した文字、compose が変換中の文字(IME)。
    external=True は、文字の入力を画面の外(ブラウザの入力欄)が受け持つ印(Python側は text を写し取るだけ)。"""

    def __init__(self, maxlen, allowed=None, text="", external=False):
        self.external = external
        self.maxlen = maxlen
        self.allowed = allowed
        self.text = clean_text(text, maxlen, allowed)
        self.compose = ""
        self.active = True

    def insert(self, s):
        for ch in s:
            if len(self.text) >= self.maxlen:
                break
            if ch >= " " and (self.allowed is None or self.allowed(ch)):
                self.text += ch
        self.compose = ""

    def backspace(self):
        self.text = self.text[:-1]

    def set_compose(self, s):
        self.compose = clean_text(s, self.maxlen, self.allowed)[:max(0, self.maxlen - len(self.text))]

    def value(self):
        return clean_text(self.text, self.maxlen, self.allowed)


def has_glyph(f, ch) -> bool:
    """フォントに ch の字形があるか(軽量フォントは使う文字しか入っていない)。f は pygame.font.Font など、metrics(ch) を持つもの。
    字形のない文字も metrics() は None を返さず、大きさ0の枠(.notdef)を返すので、それも「ない」と見なす。"""
    if ch.isspace():
        return True
    try:
        m = f.metrics(ch)
    except Exception:                                 # noqa: BLE001
        return False
    if not m or m[0] is None:
        return False
    minx, maxx, miny, maxy = m[0][:4]
    return not (minx == maxx == 0 and miny == maxy == 0)


def printable(f, text) -> str:
    """フォントにない文字を「?」に置き換えた文字列(他人が送ってきた文字を表示するとき用)。"""
    return "".join(ch if has_glyph(f, ch) else "?" for ch in text)
