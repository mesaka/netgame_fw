"""ゲーム側が書くもの(アダプター)。画面部品(NetGameScene)は、対戦の前後・チャット・準備OK・カウントダウン・一時停止を受け持ち、
対戦中の「盤面を動かす・描く」だけを、アダプターに任せる。

realtime のゲームは、RealtimeAdapter を継承して、update / draw などを書く。
turns(ロックステップ)のゲームは、TurnAdapter を継承して、on_action / state_hash / is_finished / draw などを書く。
音は、アダプターの sound(name) / bgm(name) が受け取る(鳴らさないなら、そのままでよい)。
  sound: "menu_ok"(ボタンを押した) / "menu_move"(相手のチャットが届いた) / "win" / "lose"
  bgm:   "menu"(対戦の前後) / "game"(対戦中)
"""


class GameAdapter:
    game_id = "game"                 # サーバーのアダプターと同じ ID(接続時に ?game= で送る)
    size = (480, 800)                # 画面の大きさ(NetGameScene の部品は、基準 480×800 を中央に置く)
    sess = None                      # 通信(NetSession)。NetGameScene が、接続のたびに入れる(handle など、引数にない所で使う)

    # ---- 登録 ----
    def settings(self) -> dict:
        """register に載せる設定(ランダムマッチは、同じ設定の人同士で組む)。"""
        return {}

    def settings_label(self) -> str:
        """名前入力・待機画面に出す、設定の説明(「むずかしさ: ふつう」など)。"""
        return ""

    # ---- 対戦 ----
    def start_match(self, sess):
        """新しい対戦が決まった(match が届いた)。sess.seed / sess.players / sess.settings / sess.seat で初期化する。"""

    def reset_input(self):
        """入力を全部離した状態にする(チャットの窓を開いたときなど)。"""

    def handle(self, ev):
        """対戦中のゲームの入力(キー・タッチ)。チャット入力中・確認中は呼ばれない。"""

    def update(self, sess, controls):
        """ゲームを1フレーム進める。カウントダウン・一時停止・再開待ちの間は呼ばれない。
        controls=False のときは、操作を受け付けずに進める(チャット入力中・確認中)。"""

    def local_over(self) -> bool:
        """自分の側の対戦が終わった(積み上がったなど)か。帯の表示に使う。"""
        return False

    def draw(self, sess, screen, view, frame):
        """盤面・得点・相手の様子・操作ボタンを描く。view.banner(大きい字, 色, 小さい字)は、盤面に重ねて出す。"""

    def draw_top(self, screen):
        """画面の一番手前に描くもの(エフェクトなど)。"""

    # ---- ゲーム全体の部品(音量ボタンなど) ----
    def handle_global(self, ev, phase) -> bool:
        """音量ボタンなど。処理したら True。phase: "menu"(対戦の前後) / "play"。"""
        return False

    def draw_global(self, screen, phase):
        pass

    def sound(self, name):
        pass

    def bgm(self, name):
        pass

    # ---- 名前の保存(既定は、ブラウザの localStorage。PC は保存しない) ----
    def load_name(self) -> str:
        from .webbridge import storage_get
        return storage_get("ng_name_" + self.game_id) or ""

    def save_name(self, name):
        from .webbridge import storage_set
        storage_set("ng_name_" + self.game_id, name)


class RealtimeAdapter(GameAdapter):
    """リアルタイム制(全員が同時に動く)。イベントは sess.send_event / sess.take_events で送受信する。"""


class TurnAdapter(GameAdapter):
    """ターン制(ロックステップ)。ルールはクライアントだけにある。サーバーは、手番・通し番号・ハッシュの突き合わせだけをやる。

    ゲーム側が書くもの:
      on_match(sess)               新しい対戦の用意(sess.seed / sess.players / sess.seat / sess.settings)
      on_action(seat, seq, action) サーバーから届いた手を適用する。**自分の手も、ここで適用する**(全員が同じ順で適用するため)
      state_hash()                 適用後の状態のハッシュ(64文字まで・決定的。digest() が使える)
      is_finished()                終局なら ranks([{"seat", "rank"}])、まだなら None。全員が同じ結果になること
      draw(sess, screen, view, frame) / handle(ev)   描画と入力。手は self.play(sess, action) で送る
    ルールは**決定的**にする。乱数は sess.seed から作った random.Random だけ。浮動小数・set / dict の順序に頼らない。
    手を送ったら、on_action が呼ばれるまで、自分の盤面は変えない。"""

    def __init__(self):
        self._reported = False
        self._last_seq = -1

    # ---- ゲーム側が書く ----
    def on_match(self, sess):
        pass

    def on_action(self, seat, seq, action):
        raise NotImplementedError

    def state_hash(self) -> str:
        raise NotImplementedError

    def is_finished(self):
        return None

    # ---- 使える道具 ----
    @staticmethod
    def digest(obj) -> str:
        """JSON にできる状態から、決定的なハッシュ(sha1 の16進40文字)を作る。"""
        import hashlib
        import json
        return hashlib.sha1(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

    def play(self, sess, action) -> bool:
        """自分の手を送る。手番でなければ送らない(False)。"""
        return sess.send_action(action)

    # ---- 流れ(NetGameScene から呼ばれる) ----
    def start_match(self, sess):
        self._reported = False
        self._last_seq = -1
        self.on_match(sess)

    def local_over(self):
        return self._reported

    def update(self, sess, controls):
        """届いた手を、順に適用して、ハッシュを送る。終局になったら、結果を申告する(全員の申告が一致したらサーバーが確定)。"""
        for seat, seq, action in sess.take_actions():
            if seq <= self._last_seq:                       # 同じ手が二度届いても、適用しない
                continue
            self._last_seq = seq
            self.on_action(seat, seq, action)
            sess.send_sync(seq, self.state_hash())
            if not self._reported:
                ranks = self.is_finished()
                if ranks:
                    self._reported = True
                    sess.report_finish(ranks)
