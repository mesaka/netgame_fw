// ポコテン(mesaka/pokoten)のサーバー側アダプター。realtime 方式の見本。
// ポコテンの現在の通信(attack / snap / over)を、v1 のイベントとして登録する。
const DIFFS = ["easy", "normal", "hard"];

export default {
  id: "pokoten",
  mode: "realtime",
  minPlayers: 2,
  maxPlayers: 2,
  // 組み合わせの条件: 同じむずかしさの人どうし(ルームでは、作った人の設定になる)
  normalizeSettings: (s) => ({ diff: DIFFS.includes(s && s.diff) ? s.diff : "normal" }),
  matchKey: (settings) => settings.diff,
  events: {
    // 消去1回ごとに、相手へ岩を送る
    attack: {
      to: "others",
      maxPerSec: 30,
      validate: (d) => Number.isInteger(d.n) && d.n >= 1 && d.n <= 6,
    },
    // 相手の小さな盤面(6列×12行 × (色, 数字))と、スコア・降る予定の岩
    snap: {
      to: "others",
      maxPerSec: 30,
      validate: (d) => typeof d.b === "string" && /^[.0-9]{144}$/.test(d.b)
        && Number.isInteger(d.sc) && d.sc >= 0 && d.sc <= 99999999 && Number.isInteger(d.g) && d.g >= 0 && d.g <= 999,
    },
    // 自分が積み上がった。先に届いた人が負け(同時は先着。引き分けなし)
    over: {
      to: "none",
      on: (room, seat) => room.finish(room.players.map((p) => ({ seat: p.seat, rank: p.seat === seat ? 2 : 1 }))),
    },
  },
};
