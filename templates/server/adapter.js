// サーバー側のアダプター(ゲームごとに書く)。docs/adapter.md を参照。
// realtime(リアルタイム)の例。ターン制は examples/tictactoe/adapter.js、3人用は examples/guess3/adapter.js を見る。
export default {
  id: "mygame",                 // クライアントの game_id と同じ
  mode: "realtime",             // "realtime" | "turns"
  minPlayers: 2,
  maxPlayers: 2,
  // 設定の正規化(ランダムマッチの条件・ルームでは作った人の設定になる)
  normalizeSettings: (s) => ({ level: ["easy", "normal", "hard"].includes(s && s.level) ? s.level : "normal" }),
  matchKey: (settings) => settings.level,       // 同じ値の人どうしを組み合わせる
  events: {
    // 相手へ中継するイベント。validate で形・範囲を確かめ、maxPerSec で回数を制限する
    move: { to: "others", maxPerSec: 30, validate: (d) => Number.isInteger(d.x) && d.x >= 0 && d.x < 100 },
    // 自分が負けた。結果を確定する(rank 1 = 勝ち)
    lose: { to: "none", on: (room, seat) => room.finish(room.players.map((p) => ({ seat: p.seat, rank: p.seat === seat ? 2 : 1 }))) },
  },
};
