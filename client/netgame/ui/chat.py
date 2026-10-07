"""チャットの定型文の選び方(場面にふさわしい候補を、あらかじめ選んでおく)。定型文は、文言 chat_t0〜chat_t8。"""
N_TEMPLATES = 9
T_HELLO, T_WIN, T_LOSE, T_THANKS = 0, 4, 5, 6      # よろしくお願いします。/ 勝利！！/ 負けた・・・/ ありがとうございました。


def suggest_template(phase: str, sent_end: bool = False) -> int:
    """phase: "start"(対戦開始) / "win" / "lose" / "draw"(終了後)。終了後に1つ送ったら、次はお礼を勧める。"""
    if phase == "win":
        return T_THANKS if sent_end else T_WIN
    if phase == "lose":
        return T_THANKS if sent_end else T_LOSE
    if phase == "draw":
        return T_THANKS
    return T_HELLO
