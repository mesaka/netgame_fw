"""通信プロトコルの定数と、入力の検査(pygame非依存)。仕様は docs/protocol.md(v1 と、追加の v2)。"""
from __future__ import annotations

PROTOCOL_VERSION = 1              # 既定の版(v1)。サーバー権威型(authoritative)は v=2: NetSession(version=2)
MAX_PROTOCOL_VERSION = 2

# 制限の既定(サーバーが hello の config.limits で知らせる値のほうが優先)
MAX_NAME = 8                     # プレイヤーネーム(全角8文字まで)
MAX_CHAT = 30                    # チャット(全角30文字まで)
PASS_LEN = 4                     # ルームのパスワード(4桁の数字)
ROOM_LEN = 6                     # ルームID(サーバーが発行する6桁の数字。v=2 のゲームは hello の config.rooms.code で決まる)
ROOM_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 4文字の部屋コード(alnum4)に使う文字(紛らわしい文字を除く)

# 時間(秒)
CONNECT_TIMEOUT = 12.0           # 接続できるまで待つ
PING_INTERVAL = 20.0             # 生存確認を送る間隔。何も送らないと、途中の装置に切られることがある
PAUSE_MAX = 30.0                 # チャットで止めていられる最長。過ぎたら自動で再開する(止めっぱなし対策)
FREE_TIME = 180.0                # 決着後、操作がなくても部屋にいられる時間(チャットの自由時間・3分)
IDLE_GRACE = 30.0                # 自由時間のあと、何も操作しなかったら退出になるまでの秒数(操作のたびに延びる)
LEAVE_TIMEOUT = 60.0             # 相手が退出したあと、「タイトルに戻る」が押されなくても、自動で戻るまでの秒数

COUNTDOWN_SECONDS = 5            # 全員が準備OKを押してから始まるまでのカウントダウン(画面の流れの既定)

# 登録に関するエラー(登録されないまま、やり直せる)
RETRY_ERRORS = ("name", "key", "room", "pass")


def clean_room_code(s, kind="digits6") -> str:
    """部屋コードの形が正しければ(alnum4 は大文字にして)そのまま、違えば ""。"""
    s = str(s)
    if kind == "alnum4":
        s = s.upper()
        return s if len(s) == 4 and all(ch in ROOM_CHARS for ch in s) else ""
    return clean_digits(s, ROOM_LEN)


def clean_digits(s, n) -> str:
    """半角の数字ちょうど n 桁ならそのまま、違えば ""。"""
    s = str(s)
    return s if len(s) == n and s.isascii() and s.isdigit() else ""


def valid_ranks(ranks, n_players: int) -> bool:
    """順位の形: [{seat, rank}] が、全員分(席が重ならず、rank は1以上の整数)。"""
    if not isinstance(ranks, list) or len(ranks) != n_players:
        return False
    seats = set()
    for r in ranks:
        if not isinstance(r, dict):
            return False
        seat, rank = r.get("seat"), r.get("rank")
        if (not isinstance(seat, int) or isinstance(seat, bool) or not 0 <= seat < n_players or seat in seats
                or not isinstance(rank, int) or isinstance(rank, bool) or rank < 1):
            return False
        seats.add(seat)
    return True


def rank_of(ranks, seat):
    """席の順位(なければ None)。"""
    for r in ranks or []:
        if r.get("seat") == seat:
            return r.get("rank")
    return None


def winners(ranks):
    """1位の席の一覧。"""
    return [r["seat"] for r in ranks or [] if r.get("rank") == 1]
