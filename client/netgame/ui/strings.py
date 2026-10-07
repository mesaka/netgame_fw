"""画面の文言。既定は日本語(strings_ja.py)。ゲーム側は、足りない・変えたい分だけ上書きする。"""
from ..strings_ja import STRINGS_JA


class Strings:
    def __init__(self, overrides=None):
        self.table = dict(STRINGS_JA)
        if overrides:
            self.table.update(overrides)

    def __getitem__(self, key):
        return self.table.get(key, key)

    def get(self, key, default=None):
        return self.table.get(key, default)

    def fmt(self, key, **kw):
        try:
            return self[key].format(**kw)
        except (KeyError, IndexError):
            return self[key]
