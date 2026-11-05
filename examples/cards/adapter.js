// カード(サーバー権威型 authoritative の見本)。ルールと状態はサーバーだけが持ち、各席には、その席の view だけを送る。
// 詳しくは docs/adapter.md 1.3 と docs/protocol.md 9。本物の Workers で確かめる: examples/cards/e2e.mjs
export default {
  id: "cards", mode: "authoritative", minPlayers: 2, maxPlayers: 2,
  matchKey: () => "all",
  flow: { ready: false, rematch: "game" },         // 部屋が決まったらすぐ始める。「もう一度」はゲームの手(again)で
  rooms: { code: "alnum4", password: "none" },
  events: { stamp: { to: "others", maxPerSec: 3, validate: (d) => Number.isInteger(d.id) && d.id >= 0 && d.id < 8 } },
  game: {
    init: (ctx) => ({ hands: [0, 1].map(() => [0, 1, 2].map(() => Math.floor(ctx.rng() * 10))), played: [[], []], draws: [] }),
    startEvents: () => [{ t: "deal" }],
    apply(s, seat, a, ctx) {
      if (a.type === "play") {
        const i = s.hands[seat].indexOf(a.n);
        if (i < 0) return { ok: false, error: "no-card" };
        s.hands[seat].splice(i, 1);
        s.played[seat].push(a.n);
        return { ok: true, events: [{ t: "played", seat, n: a.n }] };
      }
      if (a.type === "draw") { s.draws.push(Math.floor(ctx.rng() * 1000)); return { ok: true, events: [] }; }   // 乱数の続きの確認用
      if (a.type === "again") {                         // ゲームの中で、次の対戦へ
        s.hands = [0, 1].map(() => [0, 1, 2].map(() => Math.floor(ctx.rng() * 10)));
        s.played = [[], []];
        return { ok: true, events: [{ t: "deal" }] };
      }
      return { ok: false, error: "bad-action" };
    },
    view: (s, seat) => ({ hand: [...s.hands[seat]], oppCount: s.hands[1 - seat].length, played: s.played, draws: s.draws }),
    outcome(s) {
      if (s.hands[0].length || s.hands[1].length) return null;
      const sum = (x) => x.reduce((p, q) => p + q, 0);
      const [a, b] = [sum(s.played[0]), sum(s.played[1])];
      return { ranks: [{ seat: 0, rank: a >= b ? 1 : 2 }, { seat: 1, rank: b >= a ? 1 : 2 }] };
    },
  },
};
