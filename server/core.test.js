import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "./testkit.js";
import { PROTOCOL_VERSION } from "./core.js";

// ---- テスト用のゲーム ----
const duel = {                       // realtime・2人
  id: "duel", mode: "realtime", minPlayers: 2, maxPlayers: 2,
  normalizeSettings: (s) => ({ lv: s && s.lv === "hard" ? "hard" : "easy" }),
  matchKey: (s) => s.lv,
  events: {
    hit: { to: "others", maxPerSec: 3, validate: (d) => Number.isInteger(d.n) && d.n >= 1 && d.n <= 6 },
    quit: { to: "none", on: (room, seat) => room.finish(room.players.map((p) => ({ seat: p.seat, rank: p.seat === seat ? 2 : 1 }))) },
    note: { to: "none" },
  },
  onFinish: (room, seat, ranks) => ranks,
};
const trio = {                       // realtime・3人(N人の部屋・席・名簿の確認用)
  id: "trio", mode: "realtime", minPlayers: 3, maxPlayers: 3,
  matchKey: () => "all",
  events: { ping: { to: "others" } },
};
const ttt = {                        // turns・2人
  id: "ttt", mode: "turns", minPlayers: 2, maxPlayers: 2,
  matchKey: () => "all",
  turns: { maxActionBytes: 64 },
};
const GAMES = { duel, trio, ttt };
const mk = () => setup(GAMES);

/** 2人を、ランダムで組ませて、準備OKまで押した状態にする */
function startDuel(env, lv = "easy") {
  const a = env.open("duel"); const b = env.open("duel");
  env.say(a, { t: "register", name: "あ", mode: "random", settings: { lv } });
  env.say(b, { t: "register", name: "い", mode: "random", settings: { lv } });
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  return [a, b];
}

test("接続: hello に、接続ID・版・設定が入る。IDは重ならない", () => {
  const env = mk();
  const ids = new Set();
  for (let i = 0; i < 50; i++) {
    const w = env.open("duel");
    const h = w.last("hello");
    assert.match(h.id, /^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
    assert.equal(h.v, PROTOCOL_VERSION);
    assert.deepEqual([h.config.min_players, h.config.max_players, h.config.mode], [2, 2, "realtime"]);
    assert.equal(h.config.limits.chat, 30);
    ids.add(h.id);
  }
  assert.equal(ids.size, 50);
});

test("接続: 知らないゲーム・版が違う場合は error を返して閉じる", () => {
  const env = mk();
  const a = env.open("nope");
  assert.equal(a.last("error").code, "game");
  assert.ok(a.closed);
  const b = env.open("duel", { v: "9" });
  assert.equal(b.last("error").code, "version");
  assert.ok(b.closed);
  const c = env.open("duel", { v: "1" });
  assert.ok(c.last("hello"));
});

test("ランダム: 同じ組み合わせ条件の2人が組まれ、席は待っていた順。同じ seed・名簿", () => {
  const env = mk();
  const a = env.open("duel");
  env.say(a, { t: "register", name: "たろう", mode: "random", settings: { lv: "hard" } });
  assert.equal(a.last("registered").name, "たろう");
  assert.ok(a.last("waiting"));
  assert.equal(a.last("match"), undefined);
  const b = env.open("duel");
  env.say(b, { t: "register", name: "はなこ", mode: "random", settings: { lv: "hard" } });
  const ma = a.last("match"); const mb = b.last("match");
  assert.equal(ma.seed, mb.seed);
  assert.deepEqual([ma.you, mb.you], [0, 1]);
  assert.deepEqual(ma.players, [{ seat: 0, name: "たろう" }, { seat: 1, name: "はなこ" }]);
  assert.deepEqual(ma.settings, { lv: "hard" });
  assert.equal(ma.mode, "realtime");
});

test("ランダム: 条件が違う人・ほかのゲームの人とは組まない", () => {
  const env = mk();
  const a = env.open("duel"); const b = env.open("duel"); const c = env.open("ttt");
  env.say(a, { t: "register", name: "a", mode: "random", settings: { lv: "easy" } });
  env.say(b, { t: "register", name: "b", mode: "random", settings: { lv: "hard" } });
  env.say(c, { t: "register", name: "c", mode: "random" });
  assert.equal(a.last("match"), undefined);
  assert.equal(b.last("match"), undefined);
  assert.equal(c.last("match"), undefined);
});

test("ランダム: 3人のゲームは、3人そろうまで始まらない(席は待った順)", () => {
  const env = mk();
  const ws = [0, 1, 2].map((i) => env.open("trio"));
  env.say(ws[0], { t: "register", name: "a", mode: "random" });
  env.say(ws[1], { t: "register", name: "b", mode: "random" });
  assert.equal(ws[0].last("match"), undefined);
  assert.equal(ws[1].last("match"), undefined);
  env.say(ws[2], { t: "register", name: "c", mode: "random" });
  assert.deepEqual(ws.map((w) => w.last("match").you), [0, 1, 2]);
  assert.equal(ws[0].last("match").players.length, 3);
});

test("登録: 名前が空・長すぎ・登録済みの再登録", () => {
  const env = mk();
  const a = env.open("duel");
  env.say(a, { t: "register", name: " \n ", mode: "random" });
  assert.equal(a.last("error").code, "name");
  env.say(a, { t: "register", name: "あ".repeat(20), mode: "random" });
  assert.equal(a.last("registered").name.length, 8);
  const n = a.out.length;
  env.say(a, { t: "register", name: "別名", mode: "random" });
  assert.equal(a.out.length, n);
});

test("準備OK: 全員が押すまで始まらない。押すたびに ready_state。始まるまでイベントは中継しない", () => {
  const env = mk();
  const a = env.open("duel"); const b = env.open("duel");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  env.say(a, { t: "event", k: "hit", d: { n: 1 } });
  env.say(a, { t: "event", k: "quit", d: {} });
  assert.equal(b.last("event"), undefined);
  assert.equal(b.last("result"), undefined);
  env.say(a, { t: "ready" });
  assert.deepEqual(b.last("ready_state").seats, [0]);
  assert.equal(a.last("start"), undefined);
  env.say(a, { t: "ready" });                                 // 二度押しても同じ
  assert.equal(b.all("ready_state").length, 1);
  env.say(b, { t: "ready" });
  assert.ok(a.last("start") && b.last("start"));
  assert.equal(a.last("start").turn, undefined);
  env.say(a, { t: "event", k: "hit", d: { n: 1 } });
  assert.deepEqual(b.last("event"), { t: "event", seat: 0, k: "hit", d: { n: 1 } });
});

test("イベント(realtime): 登録のあるものだけ、検証を通ったものだけ、他の席へ。自分には返らない", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  env.say(a, { t: "event", k: "hit", d: { n: 2 } });
  assert.equal(b.all("event").length, 1);
  assert.equal(a.last("event"), undefined);
  env.say(a, { t: "event", k: "hit", d: { n: 99 } });          // 検証に通らない
  env.say(a, { t: "event", k: "bogus", d: {} });               // 登録がない
  assert.equal(a.last("error").code, "state");
  env.say(a, { t: "event", k: "note", d: { x: 1 } });          // to: "none" は中継しない
  assert.equal(b.all("event").length, 1);
});

test("イベント: 回数の上限(maxPerSec)と、1秒たてば戻ること", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  for (let i = 0; i < 3; i++) env.say(a, { t: "event", k: "hit", d: { n: 1 } });
  assert.equal(b.all("event").length, 3);
  env.say(a, { t: "event", k: "hit", d: { n: 1 } });
  assert.equal(a.last("error").code, "rate");
  assert.equal(b.all("event").length, 3);
  env.tick(1100);
  env.say(a, { t: "event", k: "hit", d: { n: 1 } });
  assert.equal(b.all("event").length, 4);
});

test("結果: アダプターが room.finish で順位を確定する。そのあとのイベントは届かない", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  env.say(a, { t: "event", k: "quit", d: {} });
  const ra = a.last("result"); const rb = b.last("result");
  assert.deepEqual(ra, { t: "result", ranks: [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }], why: "normal" });
  assert.deepEqual(rb, ra);
  env.say(b, { t: "event", k: "hit", d: { n: 1 } });
  assert.equal(a.last("event"), undefined);
  env.say(b, { t: "event", k: "quit", d: {} });                // 二重には決まらない
  assert.equal(b.all("result").length, 1);
});

test("結果: クライアントの finish は、アダプターの onFinish が通したものだけ。順位の形も検査する", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  env.say(a, { t: "finish", ranks: [{ seat: 0, rank: 1 }] });                       // 人数が合わない
  env.say(a, { t: "finish", ranks: [{ seat: 0, rank: 1 }, { seat: 0, rank: 2 }] }); // 席が重なる
  env.say(a, { t: "finish", ranks: [{ seat: 0, rank: 0 }, { seat: 1, rank: 1 }] }); // 順位が1未満
  assert.equal(b.last("result"), undefined);
  env.say(a, { t: "finish", ranks: [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }] });
  assert.deepEqual(b.last("result").ranks, [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }]);
});

test("一時停止: 対戦中だけ、止めた席・再開した席を、他の席へ中継する", () => {
  const env = mk();
  const a = env.open("duel"); const b = env.open("duel");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  env.say(a, { t: "pause", on: true });
  assert.equal(b.last("paused"), undefined);                  // 準備中は無視
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  env.say(a, { t: "pause", on: true });
  assert.deepEqual(b.last("paused"), { t: "paused", seat: 0, on: true });
  assert.equal(a.last("paused"), undefined);
  env.say(a, { t: "pause", on: false });
  assert.equal(b.last("paused").on, false);
  env.say(a, { t: "pause", on: "yes" });                      // true 以外は「再開」扱い
  assert.equal(b.last("paused").on, false);
});

test("チャット: 準備中・対戦中・決着後に、全員へ(本人にも)。30文字で切る。連投は止める。待機中はできない", () => {
  const env = mk();
  const a = env.open("duel"); const b = env.open("duel");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(a, { t: "chat", text: "こんにちは" });
  assert.equal(a.last("chat"), undefined);                    // 待機中
  env.say(b, { t: "register", name: "い", mode: "random" });
  env.say(a, { t: "chat", text: "あ".repeat(50) });
  assert.equal(b.last("chat").text.length, 30);
  assert.deepEqual([a.last("chat").seat, a.last("chat").name], [0, "あ"]);
  env.say(a, { t: "chat", text: "すぐ" });
  assert.equal(b.all("chat").length, 1);
  env.tick(500);
  env.say(a, { t: "chat", text: "あとで" });
  assert.equal(b.all("chat").length, 2);
  env.say(b, { t: "chat", text: "   " });
  assert.equal(a.all("chat").length, 2);
});

test("再戦: 全員が押したら新しい seed で、準備OKからやり直す", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  env.say(a, { t: "rematch" });                               // 対戦中は無視
  assert.equal(b.last("rematch_req"), undefined);
  env.say(a, { t: "event", k: "quit", d: {} });
  env.say(a, { t: "rematch" });
  assert.deepEqual(b.last("rematch_req"), { t: "rematch_req", seat: 0 });
  assert.equal(a.all("match").length, 1);
  env.say(b, { t: "rematch" });
  assert.equal(a.all("match").length, 2);
  assert.equal(a.all("match")[1].seed, b.all("match")[1].seed);
  env.say(b, { t: "event", k: "hit", d: { n: 1 } });          // まだ準備中
  assert.equal(a.last("event"), undefined);
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  assert.equal(a.all("start").length, 2);
  env.say(b, { t: "event", k: "hit", d: { n: 1 } });
  assert.ok(a.last("event"));
});

test("退出: 準備中・対戦中に相手が切れたら、残りの勝ち(why: left)", () => {
  const env = mk();
  let a = env.open("duel"); let b = env.open("duel");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  env.close(a);                                                // 準備中
  assert.deepEqual(b.last("result"), { t: "result", ranks: [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }], why: "left" });
  [a, b] = startDuel(env);                                     // 対戦中
  env.close(b);
  assert.equal(a.last("result").why, "left");
  assert.deepEqual(a.last("result").ranks, [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }]);
});

test("退出: 決着後に切れたら player_left。再戦はできない。全員が抜けたら部屋の記録は消える", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  env.say(a, { t: "event", k: "quit", d: {} });
  env.close(a);
  assert.deepEqual(b.last("player_left"), { t: "player_left", seat: 0 });
  env.say(b, { t: "rematch" });
  assert.equal(b.all("match").length, 1);
  assert.equal(env.rooms().length, 1);
  env.close(b);
  assert.equal(env.rooms().length, 0);
});

test("退出: leave を送ると、部屋から出て、もう一度登録できる", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  env.say(a, { t: "event", k: "quit", d: {} });
  env.say(a, { t: "leave" });
  assert.deepEqual(b.last("player_left"), { t: "player_left", seat: 0 });
  env.say(a, { t: "register", name: "あ2", mode: "random" });
  assert.equal(a.last("registered").name, "あ2");
});

test("壊れたメッセージ・大きすぎるメッセージ・知らない種類は無視する", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  const n = b.out.length;
  env.core.onMessage(a, "{not json");
  env.core.onMessage(a, "x".repeat(20000));
  env.core.onMessage(a, JSON.stringify({ t: 5 }));
  env.core.onMessage(a, JSON.stringify({ t: "unknown" }));
  env.core.onMessage(a, JSON.stringify([1, 2]));
  assert.equal(b.out.length, n);
});

// ---- ルーム(ルームID + パスワード) ----
function makeRoom(env, game = "duel", pass = "0427", settings = { lv: "hard" }) {
  const host = env.open(game);
  env.say(host, { t: "register", name: "ホスト", mode: "friend", pass, settings });
  return [host, host.last("waiting").room];
}

test("ルーム: サーバーがルームIDを発行し、ルームIDとパスワードが合えば組まれる。設定は作った人のもの", () => {
  const env = mk();
  const [host, room] = makeRoom(env);
  assert.match(room, /^[0-9]{6}$/);
  assert.notEqual(room, host.last("hello").id);                // 接続IDとは別物
  const guest = env.open("duel");
  env.say(guest, { t: "register", name: "ゲスト", mode: "friend", room, pass: "0427", settings: { lv: "easy" } });
  assert.equal(guest.last("registered").name, "ゲスト");
  assert.deepEqual(host.last("match").players, [{ seat: 0, name: "ホスト" }, { seat: 1, name: "ゲスト" }]);
  assert.deepEqual(guest.last("match").settings, { lv: "hard" });
  assert.equal(host.last("match").seed, guest.last("match").seed);
  assert.deepEqual([host.last("match").you, guest.last("match").you], [0, 1]);
});

test("ルーム: ルームIDは重ならない。パスワードは同じでもよい", () => {
  const env = mk();
  const rooms = new Set();
  for (let i = 0; i < 30; i++) rooms.add(makeRoom(env, "duel", "1111")[1]);
  assert.equal(rooms.size, 30);
});

test("ルーム: パスワードが違うと入れず、登録もされない。合えばやり直せる", () => {
  const env = mk();
  const [host, room] = makeRoom(env);
  const g = env.open("duel");
  env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "9999" });
  assert.equal(g.last("error").code, "pass");
  assert.equal(g.last("registered"), undefined);
  assert.equal(host.last("match"), undefined);
  env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "0427" });
  assert.ok(g.last("match"));
});

test("ルーム: パスワードを5回間違えると、その部屋は閉じる(正しくても入れない)", () => {
  const env = mk();
  const [host, room] = makeRoom(env);
  const g = env.open("duel");
  for (let i = 0; i < 5; i++) {
    env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "000" + i });
    assert.equal(g.last("error").code, "pass");
  }
  env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "0427" });
  assert.equal(g.last("error").code, "room");
  assert.equal(host.last("match"), undefined);
});

test("ルーム: ない・形が違う・対戦中・別のゲーム・ランダム待ちには入れない", () => {
  const env = mk();
  const rnd = env.open("duel"); env.say(rnd, { t: "register", name: "r", mode: "random" });
  const [, room] = makeRoom(env);
  const other = makeRoom(env, "ttt")[1];
  const g = env.open("duel");
  for (const r of ["999999", "123", "abcdef", rnd.last("hello").id, "1234567", other]) {
    env.say(g, { t: "register", name: "g", mode: "friend", room: r, pass: "0427" });
    assert.equal(g.last("error").code, "room");
  }
  env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "0427" });
  assert.ok(g.last("match"));
  const late = env.open("duel");
  env.say(late, { t: "register", name: "l", mode: "friend", room, pass: "0427" });
  assert.equal(late.last("error").code, "room");                // 対戦が始まったルームには入れない
});

test("ルーム: パスワードは4桁の数字だけ", () => {
  const env = mk();
  const a = env.open("duel");
  for (const pass of ["12", "abcd", "", undefined, "12345"]) {
    env.say(a, { t: "register", name: "a", mode: "friend", pass });
    assert.equal(a.last("error").code, "key");
  }
  assert.equal(a.last("waiting"), undefined);
});

test("ルーム: 待っている間に作った人が抜けたら、部屋は消える。ルームで待つ人は、ランダムの相手にならない", () => {
  const env = mk();
  const [host, room] = makeRoom(env);
  const r = env.open("duel"); env.say(r, { t: "register", name: "r", mode: "random", settings: { lv: "hard" } });
  assert.equal(r.last("match"), undefined);
  assert.equal(host.last("match"), undefined);
  env.close(host);
  assert.equal(env.rooms().length, 0);
  const g = env.open("duel");
  env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "0427" });
  assert.equal(g.last("error").code, "room");
});

test("ルーム: 3人のゲームは、満員(3人目が入る)で始まる", () => {
  const env = mk();
  const [host, room] = makeRoom(env, "trio");
  const g1 = env.open("trio"); const g2 = env.open("trio");
  env.say(g1, { t: "register", name: "b", mode: "friend", room, pass: "0427" });
  assert.equal(g1.last("waiting").room, room);
  assert.equal(host.last("match"), undefined);
  env.say(g2, { t: "register", name: "c", mode: "friend", room, pass: "0427" });
  assert.deepEqual([host, g1, g2].map((w) => w.last("match").you), [0, 1, 2]);
});

// ---- 3人の部屋(席・名簿・一時停止・イベントの中継) ----
test("3人: ready_state は押した席の一覧。全員そろったら start。イベントは自分以外の全員へ", () => {
  const env = mk();
  const ws = [0, 1, 2].map(() => env.open("trio"));
  ws.forEach((w, i) => env.say(w, { t: "register", name: "p" + i, mode: "random" }));
  env.say(ws[2], { t: "ready" });
  env.say(ws[0], { t: "ready" });
  assert.deepEqual(ws[1].last("ready_state").seats, [0, 2]);
  assert.equal(ws[0].last("start"), undefined);
  env.say(ws[1], { t: "ready" });
  assert.ok(ws.every((w) => w.last("start")));
  env.say(ws[1], { t: "event", k: "ping", d: { x: 1 } });
  assert.equal(ws[0].last("event").seat, 1);
  assert.equal(ws[2].last("event").seat, 1);
  assert.equal(ws[1].last("event"), undefined);
  env.say(ws[0], { t: "pause", on: true });
  assert.ok(ws[1].last("paused").on && ws[2].last("paused").on);
});

test("3人: 対戦中に1人が抜けると(いまは)中止。結果は why: abort", () => {
  const env = mk();
  const ws = [0, 1, 2].map(() => env.open("trio"));
  ws.forEach((w, i) => env.say(w, { t: "register", name: "p" + i, mode: "random" }));
  ws.forEach((w) => env.say(w, { t: "ready" }));
  env.close(ws[1]);
  const r = ws[0].last("result");
  assert.equal(r.why, "abort");
  assert.deepEqual(r.ranks.map((x) => x.seat), [0, 2]);
  assert.ok(ws[2].last("result"));
});

// ---- turns(ロックステップ) ----
function startTtt(env) {
  const a = env.open("ttt"); const b = env.open("ttt");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  return [a, b];
}

test("turns: start に最初の手番が入る。手番の席だけが、seq の合う手を送れる", () => {
  const env = mk();
  const [a, b] = startTtt(env);
  assert.deepEqual(a.last("start").turn, { seat: 0, seq: 0 });
  assert.equal(a.last("match").mode, "turns");
  env.say(b, { t: "action", seq: 0, d: { x: 1 } });            // 手番ではない
  assert.equal(b.last("error").code, "state");
  env.say(a, { t: "action", seq: 5, d: { x: 1 } });            // seq が違う
  assert.equal(a.last("error").code, "state");
  assert.equal(b.last("action"), undefined);
  env.say(a, { t: "action", seq: 0, d: { x: 1 } });
  for (const w of [a, b]) {                                     // 本人にも返る
    assert.deepEqual(w.last("action"), { t: "action", seat: 0, seq: 0, d: { x: 1 } });
    assert.deepEqual(w.last("turn"), { t: "turn", seat: 1, seq: 1 });
  }
  env.say(a, { t: "action", seq: 1, d: { x: 2 } });            // もう手番ではない
  assert.equal(a.last("error").code, "state");
  env.say(b, { t: "action", seq: 1, d: { x: 2 } });
  assert.deepEqual(a.last("turn"), { t: "turn", seat: 0, seq: 2 });
});

test("turns: 大きすぎる手は捨てる。events は使えない", () => {
  const env = mk();
  const [a, b] = startTtt(env);
  env.say(a, { t: "action", seq: 0, d: { s: "x".repeat(100) } });
  assert.equal(a.last("error").code, "rate");
  assert.equal(b.last("action"), undefined);
  env.say(a, { t: "event", k: "hit", d: {} });
  assert.equal(b.last("event"), undefined);
});

test("turns: 全員のハッシュが一致すれば何も起きない。食い違えば desync で中止", () => {
  const env = mk();
  const [a, b] = startTtt(env);
  env.say(a, { t: "action", seq: 0, d: { x: 1 } });
  env.say(a, { t: "sync", seq: 0, h: "abc" });
  env.say(b, { t: "sync", seq: 0, h: "abc" });
  assert.equal(a.last("desync"), undefined);
  env.say(b, { t: "action", seq: 1, d: { x: 2 } });
  env.say(a, { t: "sync", seq: 1, h: "aaa" });
  env.say(b, { t: "sync", seq: 1, h: "bbb" });
  assert.deepEqual(a.last("desync"), { t: "desync", seq: 1 });
  assert.equal(b.last("result").why, "desync");
});

test("turns: まだ指されていない手のハッシュ・長すぎるハッシュは無視する", () => {
  const env = mk();
  const [a, b] = startTtt(env);
  env.say(a, { t: "sync", seq: 0, h: "abc" });
  env.say(b, { t: "sync", seq: 0, h: "zzz" });
  assert.equal(a.last("desync"), undefined);
  env.say(a, { t: "action", seq: 0, d: {} });
  env.say(a, { t: "sync", seq: 0, h: "x".repeat(100) });
  env.say(b, { t: "sync", seq: 0, h: "zzz" });
  assert.equal(a.last("desync"), undefined);
});

test("turns: 全員の finish が一致すれば確定。食い違えば desync", () => {
  const env = mk();
  let [a, b] = startTtt(env);
  const ranks = [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }];
  env.say(a, { t: "finish", ranks });
  assert.equal(b.last("result"), undefined);
  env.say(b, { t: "finish", ranks: [{ seat: 1, rank: 2 }, { seat: 0, rank: 1 }] });   // 並びが違っても、内容が同じならよい
  assert.deepEqual(a.last("result"), { t: "result", ranks, why: "normal" });
  [a, b] = startTtt(env);
  env.say(a, { t: "finish", ranks });
  env.say(b, { t: "finish", ranks: [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }] });
  assert.ok(a.last("desync"));
  assert.equal(a.last("result").why, "desync");
});

test("turns: 結果が出たあとは手を受け付けない。再戦で、手番は最初から", () => {
  const env = mk();
  const [a, b] = startTtt(env);
  const ranks = [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }];
  env.say(a, { t: "finish", ranks }); env.say(b, { t: "finish", ranks });
  env.say(a, { t: "action", seq: 0, d: {} });
  assert.equal(b.last("action"), undefined);
  env.say(a, { t: "rematch" }); env.say(b, { t: "rematch" });
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  assert.deepEqual(a.all("start")[1].turn, { seat: 0, seq: 0 });
});

test("turns: 手番の人が抜けたら、残りの勝ち", () => {
  const env = mk();
  const [a, b] = startTtt(env);
  env.close(a);
  assert.deepEqual(b.last("result").ranks, [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }]);
  assert.equal(b.last("result").why, "left");
});

test("turns: アダプターの nextTurn / validate / firstTurn を使える", () => {
  const env = setup({
    g: { id: "g", mode: "turns", minPlayers: 2, maxPlayers: 2, matchKey: () => "k",
         turns: { firstTurn: () => 1, nextTurn: (room, seat, d) => (d.again ? seat : 1 - seat), validate: (room, seat, d) => d.ok !== false } },
  });
  const a = env.open("g"); const b = env.open("g");
  env.say(a, { t: "register", name: "a", mode: "random" });
  env.say(b, { t: "register", name: "b", mode: "random" });
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  assert.deepEqual(a.last("start").turn, { seat: 1, seq: 0 });
  env.say(b, { t: "action", seq: 0, d: { ok: false } });
  assert.equal(b.last("error").code, "rule");
  env.say(b, { t: "action", seq: 0, d: { again: true } });
  assert.deepEqual(a.last("turn"), { t: "turn", seat: 1, seq: 1 });
  env.say(b, { t: "action", seq: 1, d: {} });
  assert.deepEqual(a.last("turn"), { t: "turn", seat: 0, seq: 2 });
});

test("部屋の記録は kv に残る(Durable Object が休止しても、ソケットの付属情報だけで続けられる)", () => {
  const env = mk();
  const [a, b] = startDuel(env);
  const key = env.rooms()[0];
  const rec = JSON.parse(env.store.get(key));
  assert.equal(rec.state, "playing");
  assert.deepEqual(rec.players.map((p) => p.name), ["あ", "い"]);
  assert.ok(a.att.roomId === rec.id && b.att.roomId === rec.id);
  assert.ok(JSON.stringify(a.att).length < 400);                // 付属情報は小さい(2KBの制限に余裕)
});
