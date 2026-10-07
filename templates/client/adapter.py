"""クライアント側のアダプター(ゲームごとに書く)。docs/adapter.md を参照。リアルタイム制の骨組み。
ターン制は、TurnAdapter を継承する(見本: examples/tictactoe/ttt_client.py)。"""
import pygame

from netgame.adapter import RealtimeAdapter


class MyGameAdapter(RealtimeAdapter):
    game_id = "mygame"                 # サーバーのアダプターの id と同じ
    size = (480, 800)

    def __init__(self):
        self.game = None
        self.opp = 0

    def settings(self):
        return {"level": "normal"}     # register に載る。サーバーの normalizeSettings / matchKey と対応する

    def settings_label(self):
        return "むずかしさ: ふつう"

    def start_match(self, sess):       # 新しい対戦。sess.seed が全員同じ。乱数は seed から作る
        self.game = {"x": 0}
        self.opp = 0

    def handle(self, ev):              # 対戦中の入力(チャット入力中・確認中は呼ばれない)
        pass

    def reset_input(self):             # 押しっぱなしを離す
        pass

    def update(self, sess, controls):  # 1フレーム。カウントダウン・一時停止中は呼ばれない
        for seat, kind, data in sess.take_events():
            if kind == "move":
                self.opp = data["x"]
        if controls:
            sess.send_event("move", {"x": self.game["x"]})

    def draw(self, sess, screen, view, frame):
        screen.fill((14, 14, 28))      # view.banner(大きい字, 色, 小さい字)を盤面に重ねて出す
