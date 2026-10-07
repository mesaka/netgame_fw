"""○×のルール(pygame を使わない)。席0 = ○(先手)、席1 = ×。
手は {"cell": 0〜8}。空いていないマス・終局後の手は、**全員が同じく無視する**(サーバーは手の中身を見ないので、ずれないようにするため)。"""
LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]


class Board:
    def __init__(self):
        self.cells = [None] * 9          # None / 0(○) / 1(×)
        self.moves = 0
        self.line = None                 # 揃った3マス

    def apply(self, seat, action) -> bool:
        """手を適用する。無視した手(空いていない・終局後・形が違う)は False。"""
        cell = action.get("cell") if isinstance(action, dict) else None
        if self.winner() is not None or self.full() or not isinstance(cell, int) or isinstance(cell, bool) \
                or not 0 <= cell <= 8 or self.cells[cell] is not None or seat not in (0, 1):
            return False
        self.cells[cell] = seat
        self.moves += 1
        return True

    def winner(self):
        for a, b, c in LINES:
            if self.cells[a] is not None and self.cells[a] == self.cells[b] == self.cells[c]:
                self.line = (a, b, c)
                return self.cells[a]
        return None

    def full(self):
        return all(c is not None for c in self.cells)

    def ranks(self):
        """終局なら [{"seat", "rank"}]。勝ち=1位・負け=2位、引き分けは両方1位。まだなら None。"""
        w = self.winner()
        if w is not None:
            return [{"seat": w, "rank": 1}, {"seat": 1 - w, "rank": 2}]
        if self.full():
            return [{"seat": 0, "rank": 1}, {"seat": 1, "rank": 1}]
        return None

    def serialize(self):
        return "".join("." if c is None else str(c) for c in self.cells)
