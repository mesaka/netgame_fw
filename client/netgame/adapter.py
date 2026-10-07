"""ゲーム側が書くもの(アダプター)。画面部品(NetGameScene)は、対戦の前後・チャット・準備OK・カウントダウン・一時停止を受け持ち、
対戦中の「盤面を動かす・描く」だけを、アダプターに任せる。

realtime のゲームは、RealtimeAdapter を継承して、update / draw などを書く。
音は、アダプターの sound(name) / bgm(name) が受け取る(鳴らさないなら、そのままでよい)。
  sound: "menu_ok"(ボタンを押した) / "menu_move"(相手のチャットが届いた) / "win" / "lose"
  bgm:   "menu"(対戦の前後) / "game"(対戦中)
"""


class GameAdapter:
    game_id = "game"                 # サーバーのアダプターと同じ ID(接続時に ?game= で送る)
    size = (480, 800)                # 画面の大きさ(NetGameScene の部品は、基準 480×800 を中央に置く)

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
