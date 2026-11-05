// 再接続(v=2・authoritative): 切断の猶予・resume・presence・アラーム・休止からの復帰。
import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "./testkit.js";
import { NetGameCore } from "./core.js";
import cards from "../examples/cards/adapter.js";

const base = { ...cards, onLeave: { grace: 60, then: "forfeit" } };       // 猶予 60 秒
const slow = { ...base, id: "slow" };
const instant = { ...base, id: "instant", onLeave: { grace: 0, then: "forfeit" } };     // 猶予なし(v1 と同じ)
const framed = { ...base, id: "framed", flow: {}, rooms: { code: "digits6", password: "required" } };
const GAMES = { cards: base, slow, instant, framed };
const V2 = { v: "2" };

function pair(env, game = "cards") {
  const a = env.open(game, V2); const b = env.open(game, V2);
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  return [a, b];
}
const room = (w) => w.last("match").room;
const tok = (w) => w.last("registered").token;
const hand = (w) => w.last("state").view.hand;
const resume = (env, game, w, code, token) => {
  const n = env.open(game, V2);
  env.say(n, { t: "resume", room: code, token });
  return n;
};

test("token: v=2 の authoritative の registered にだけ付く。match や相手への通知には出ない", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  assert.match(tok(a), /^[0-9a-f]{32}$/);
  assert.notEqual(tok(a), tok(b));
  assert.match(room(a), /^[A-HJ-NP-Z2-9]{4}$/);
  assert.equal(room(a), room(b));
  for (const t of [tok(a), tok(b)]) {
    assert.ok(!JSON.stringify(a.out.filter((m) => m.t !== "registered")).includes(t), "他のメッセージに token が出ている");
    assert.ok(!JSON.stringify(b.out.filter((m) => m.t !== "registered")).includes(t));
  }
});

test("切断: すぐには退出にならない。相手に presence(offline)。対戦は続けられる。アラームが期限に予約される", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  env.close(a);
  assert.deepEqual(b.last("presence"), { t: "presence", seat: 0, online: false });
  assert.equal(b.last("result"), undefined);
  assert.equal(env.alarm(), 1000 + 60000);
  const n = hand(b)[0];
  env.say(b, { t: "act", a: { type: "play", n } });               // 残った人は、手を指せる
  assert.equal(b.last("state").seq, 1);
});

test("resume: 猶予のうちに戻れる。resumed と最新の view(resync)、相手に presence(online)。アラームは止まる", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  const code = room(a); const token = tok(a);
  const myHand = hand(a);
  env.close(a);
  env.say(b, { t: "act", a: { type: "play", n: hand(b)[0] } });
  env.tick(30000);
  const a2 = resume(env, "cards", a, code, token);
  const r = a2.last("resumed");
  assert.deepEqual([r.you, r.room, r.status, r.mode], [0, code, "playing", "authoritative"]);
  assert.deepEqual(r.players, [{ seat: 0, name: "あ" }, { seat: 1, name: "い" }]);
  const st = a2.last("state");
  assert.equal(st.resync, true);
  assert.equal(st.seq, 1);
  assert.deepEqual(st.view.hand, myHand);                          // 自分の手札は元のまま
  assert.equal(st.view.played[1].length, 1);                       // 留守のあいだの相手の手も見える
  assert.deepEqual(b.last("presence"), { t: "presence", seat: 0, online: true });
  assert.equal(env.alarm(), null);
  env.say(a2, { t: "act", a: { type: "play", n: myHand[0] } });    // 続きが指せる
  assert.equal(b.last("state").seq, 2);
  env.fireAlarm();                                                  // 期限が来ても、もう何も起きない
});

test("猶予切れ: アラームで退出になり、残りの人の勝ち(why: left)。席の記録・状態は消える", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  env.close(a);
  env.tick(59999);
  env.core.onAlarm();
  assert.equal(b.last("result"), undefined);                        // まだ猶予のうち
  env.tick(2);
  env.core.onAlarm();
  assert.deepEqual(b.last("result"), { t: "result", ranks: [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }], why: "left" });
  assert.equal(env.alarm(), null);
  assert.equal([...env.store.keys()].some((k) => k.startsWith("state:")), false);
  const a2 = resume(env, "cards", a, room(b), tok(a));              // 猶予切れのあとは、戻れない
  assert.equal(a2.last("error").code, "resume");
});

test("resume の失敗: 合言葉違い・部屋がない・v1・別のゲームは、どれも同じ error(resume)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  env.close(a);
  const bad = [
    resume(env, "cards", a, room(b), "0".repeat(32)),
    resume(env, "cards", a, "ZZZZ", tok(a)),
    resume(env, "cards", a, "zz", tok(a)),
    resume(env, "cards", a, room(b), ""),
  ];
  for (const w of bad) assert.deepEqual(w.out.filter((m) => m.t === "error"), [{ t: "error", code: "resume" }]);
  const v1 = env.open("cards");                                     // v1 では、そもそも authoritative に入れない
  assert.equal(v1.last("error").code, "version");
  const other = env.open("slow", V2);                               // 別のゲームの部屋には、戻れない
  env.say(other, { t: "resume", room: room(b), token: tok(a) });
  assert.equal(other.last("error").code, "resume");
  assert.equal(env.alarm(), 1000 + 60000);                          // 失敗しても、猶予はそのまま
});

test("切れたことにまだ気づいていない古い接続は、resume で入れ替わり(close 4001)、その後の close は無視される", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  let closedWith = null;
  const orig = a.close.bind(a);
  a.close = (code, reason) => { closedWith = [code, reason]; orig(); };
  const a2 = resume(env, "cards", a, room(a), tok(a));
  assert.equal(a2.last("resumed").you, 0);
  assert.deepEqual(closedWith, [4001, "replaced"]);
  env.close(a);                                                     // 古い接続の close が、遅れて届く
  assert.equal(b.last("presence")?.online, true);                   // offline にならない
  assert.equal(b.last("result"), undefined);
  assert.equal(env.alarm(), null);
  env.say(a2, { t: "act", a: { type: "play", n: hand(a2)[0] } });
  assert.equal(b.last("state").seq, 1);
});

test("明示の leave は、猶予なしですぐ退出。grace: 0 のゲームは、切断もすぐ退出(v1 と同じ)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  env.say(a, { t: "leave" });
  assert.equal(b.last("result").why, "left");
  assert.equal(env.alarm(), null);
  const env2 = setup(GAMES);
  const [c, d] = pair(env2, "instant");
  env2.close(c);
  assert.equal(d.last("result").why, "left");
  assert.equal(d.last("presence"), undefined);
});

test("待機中の部屋の作成者が切れても、猶予のあいだは部屋が残り、戻れる。猶予切れで部屋は消える", () => {
  const env = setup(GAMES);
  const h = env.open("cards", V2);
  env.say(h, { t: "register", name: "あ", mode: "friend" });
  const code = h.last("waiting").room; const token = tok(h);
  env.close(h);
  assert.equal(env.rooms().length, 1);
  const g = env.open("cards", V2);                                  // 作成者がいないあいだに、友だちが入る
  env.say(g, { t: "register", name: "い", mode: "friend", room: code });
  assert.equal(g.last("match").you, 1);
  assert.equal(g.last("state").seq, 0);
  const h2 = resume(env, "cards", h, code, token);
  assert.deepEqual([h2.last("resumed").you, h2.last("resumed").status], [0, "playing"]);
  assert.equal(h2.last("state").view.hand.length, 3);

  const env2 = setup(GAMES);
  const h3 = env2.open("cards", V2);
  env2.say(h3, { t: "register", name: "う", mode: "friend" });
  const c3 = h3.last("waiting").room;
  env2.close(h3);
  env2.tick(60001); env2.core.onAlarm();
  assert.equal(env2.rooms().length, 0);
  assert.equal(resume(env2, "cards", h3, c3, tok(h3)).last("error").code, "resume");
});

test("待機中に戻ると waiting が、準備中は ready_state が、結果のあとは result が届く(ready ありのゲーム)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "framed");
  env.say(a, { t: "ready" });
  env.close(a);
  const a2 = resume(env, "framed", a, room(a), tok(a));
  assert.equal(a2.last("resumed").status, "ready");
  assert.deepEqual(a2.last("ready_state").seats, [0]);
  env.say(a2, { t: "ready" }); env.say(b, { t: "ready" });
  for (const w of [a2, b]) for (const n of [...hand(w)]) env.say(w, { t: "act", a: { type: "play", n } });
  assert.equal(b.all("result").length, 1);
  env.close(a2);
  const a3 = resume(env, "framed", a, room(a), tok(a));
  assert.equal(a3.last("resumed").status, "over");
  assert.deepEqual(a3.last("result"), b.last("result"));
});

test("両方が切れても、どちらも戻れる。両方戻らなければ、猶予切れで部屋ごと消える", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  const [code, ta, tb] = [room(a), tok(a), tok(b)];
  const act = hand(a)[0];
  env.close(a); env.close(b);
  const a2 = resume(env, "cards", a, code, ta);
  assert.equal(a2.last("presence").online, false);                  // 戻った人に、相手がまだ切れていることを知らせる
  assert.equal(a2.last("presence").seat, 1);
  const b2 = resume(env, "cards", b, code, tb);
  assert.equal(a2.last("presence").online, true);
  env.say(a2, { t: "act", a: { type: "play", n: act } });
  assert.equal(b2.last("state").seq, 1);

  const env2 = setup(GAMES);
  const [c, d] = pair(env2);
  env2.close(c); env2.close(d);
  env2.tick(60001); env2.core.onAlarm();
  assert.equal(env2.rooms().length, 0);
  assert.equal([...env2.store.keys()].some((k) => k.startsWith("state:")), false);
  assert.equal(env2.alarm(), null);
  assert.equal(env2.store.get("gq"), "[]");
});

test("複数の部屋: アラームは、いちばん早い期限に合わせ、鳴ったら次の期限へ", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  env.tick(10000);
  const [c, d] = pair(env);
  env.close(c);                                                     // 先に切れたのは c(期限 1000+10000+60000)
  env.tick(5000);
  env.close(a);                                                     // 次に a(期限 1000+15000+60000)
  assert.equal(env.alarm(), 1000 + 10000 + 60000);
  assert.ok(env.fireAlarm());
  assert.equal(d.last("result").why, "left");
  assert.equal(b.last("result"), undefined);
  assert.equal(env.alarm(), 1000 + 15000 + 60000);
  assert.ok(env.fireAlarm());
  assert.equal(b.last("result").why, "left");
  assert.equal(env.alarm(), null);
});

test("休止: 猶予・合言葉・アラームの情報は kv にある。核を作り直しても、resume も猶予切れも動く", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  const [code, ta] = [room(a), tok(a)];
  env.close(a);
  const fresh = new NetGameCore(env.core.host, GAMES);              // Durable Object が休止して、起きた
  const a2 = env.open("cards", V2);
  fresh.onMessage(a2, JSON.stringify({ t: "resume", room: code, token: ta }));
  assert.equal(a2.last("resumed").you, 0);
  assert.equal(a2.last("state").seq, 0);
  assert.deepEqual(b.last("presence"), { t: "presence", seat: 0, online: true });
  fresh.onClose(a2);
  env.tick(60001);
  new NetGameCore(env.core.host, GAMES).onAlarm();                  // さらに別の核で、アラーム
  assert.equal(b.last("result").why, "left");
});

test("token は、他の部屋・他の席では使えない(席ごとの合言葉)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env);
  const [c, d] = pair(env);
  env.close(a);
  assert.equal(resume(env, "cards", a, room(c), tok(a)).last("error").code, "resume");     // 別の部屋のコード + a の token
  const cheat = resume(env, "cards", b, room(a), tok(c));                                  // 別の部屋の token
  assert.equal(cheat.last("error").code, "resume");
  assert.equal(b.last("result"), undefined);
});
