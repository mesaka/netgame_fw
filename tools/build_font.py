"""ゲーム用の、使う文字だけを入れた日本語フォントを作る(Web版の容量削減)。netgame の画面で使う文字・名前やチャットに入力できる文字も入れる。
  python tools/build_font.py --font 元フォント.ttf --out assets/fonts/jp.ttf [--strings ゲームの文言.py:変数名]... [--text 追加の文字] [--text-file ファイル]
  --strings: 文言の辞書(値が文字列)を持つ .py と変数名(省略時 S)。何度でも指定できる。
元フォントのライセンス(例: M PLUS Rounded 1c = SIL Open Font License)は、ゲーム側で守ること。fontTools が必要(pip install fonttools)。"""
import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "client"))

# 名前・チャットに入力できる文字(ASCII・ひらがな・カタカナ・全角英数記号)。漢字は容量が大きいので入れない
INPUT_CHARS = ("".join(chr(c) for c in list(range(0x3041, 0x3097)) + list(range(0x30A1, 0x30FB)) + list(range(0xFF01, 0xFF5F)))
               + "ー・、。「」『』〜　")
ASCII = "".join(chr(c) for c in range(0x20, 0x7F))


def load_dict(spec):
    """'path/to/strings.py:S' → その辞書の、文字列の値の一覧。"""
    path, _, name = spec.partition(":")
    mod_spec = importlib.util.spec_from_file_location("_game_strings", path)
    mod = importlib.util.module_from_spec(mod_spec)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    try:
        mod_spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    table = getattr(mod, name or "S")
    return [v for v in table.values() if isinstance(v, str)]


def collect_chars(strings_specs=(), texts=(), input_chars=True):
    """フォントに入れる文字(重複なし・整列済み)。netgame の既定の文言(strings_ja)も含む。"""
    from netgame.strings_ja import STRINGS_JA
    parts = [ASCII, "".join(STRINGS_JA.values())]
    for spec in strings_specs:
        parts.append("".join(load_dict(spec)))
    parts.extend(texts)
    if input_chars:
        parts.append(INPUT_CHARS)
    return "".join(sorted(set("".join(parts))))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--font", required=True, help="元のフォント(.ttf / .otf)")
    ap.add_argument("--out", required=True, help="出力先(.ttf)")
    ap.add_argument("--strings", action="append", default=[], help="文言の辞書: ファイル.py[:変数名]")
    ap.add_argument("--text", action="append", default=[], help="追加で入れる文字")
    ap.add_argument("--text-file", action="append", default=[], help="追加で入れる文字が書かれたファイル(UTF-8)")
    ap.add_argument("--no-input-chars", action="store_true", help="名前・チャット用の文字(かな・全角記号など)を入れない")
    a = ap.parse_args(argv)
    texts = list(a.text) + [open(p, encoding="utf-8").read() for p in a.text_file]
    chars = collect_chars(a.strings, texts, not a.no_input_chars)
    from fontTools import subset
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    subset.main([a.font, "--text=" + chars, "--output-file=" + a.out, "--no-hinting", "--layout-features=kern"])
    print(len(chars), "chars ->", os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
