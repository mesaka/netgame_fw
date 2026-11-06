// authoritative(サーバー権威型)・rooms / flow の設定・入室失敗の制限(v2)のテスト。v1 の動作は core.test.js が守る。
import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "./testkit.js";
import { NetGameCore, hashClientKey } from "./core.js";

import cards from "../examples/cards/adapter.js";
const framed = {                      // ready あり・結果のあとはフレームワークの rematch
  ...cards, id: "framed", flow: {}, rooms: { code: "digits6", password: "required" },
};
const optional = { ...cards, id: "optpass", rooms: { code: "alnum4", password: "optional" } };
const turnsStamp = {                  // turns でも events(スタンプなど)を使える
  id: "tstamp", mode: "turns", minPlayers: 2, maxPlayers: 2, matchKey: () => "all",
  turns: { maxActionBytes: 64 }, events: { stamp: { to: "others" } },
};
const GAMES = { cards, framed, optpass: optional, tstamp: turnsStamp };
const V2 = { v: "2" };

/** 2人をランダムで組ませる(ready なしのゲームは、これで対戦が始まる) */
function pair(env, game, opts = V2) {
  const a = env.open(game, opts); const b = env.open(game, opts);
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  return [a, b];
}
const handOf = (w) => w.last("state").view.hand;

test("版: authoritative のゲームは v=2 が必要。v=2 の hello に flow / rooms が入る", () => {
  const env = setup(GAMES);
  const old = env.open("cards");                 // v なし = v1
  assert.equal(old.last("error").code, "version");
  assert.ok(old.closed);
  const w = env.open("cards", V2);
  const h = w.last("hello");
  assert.equal(h.v, 2);
  assert.equal(h.config.mode, "authoritative");
  assert.deepEqual(h.config.flow, { ready: false, rematch: "game" });
  assert.deepEqual(h.config.rooms, { code: "alnum4", password: "none" });
  assert.equal(env.open("cards", { v: "3" }).last("error").code, "version");
  // v1 のゲームを v=2 で開くこともできる(hello に v=2)。v1 の hello には flow / rooms を足さない
  assert.equal(env.open("tstamp", V2).last("hello").v, 2);
  assert.equal(env.open("tstamp").last("hello").config.flow, undefined);
});

test("flow.ready=false: 部屋が決まったらすぐ start と state(seq 0・startEvents)が届く", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  for (const w of [a, b]) {
    assert.equal(w.all("match").length, 1);
    assert.equal(w.all("start").length, 1);
    const st = w.last("state");
    assert.equal(st.seq, 0);
    assert.deepEqual(st.events, [{ t: "deal" }]);
    assert.equal(st.view.hand.length, 3);
  }
  assert.ok(a.out.findIndex((m) => m.t === "start") < a.out.findIndex((m) => m.t === "state"));
});

test("flow.ready=true(既定): 全員 ready を押すまで state は届かない", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "framed");
  assert.equal(a.last("state"), undefined);
  env.say(a, { t: "ready" });
  assert.equal(a.last("state"), undefined);
  env.say(b, { t: "ready" });
  assert.equal(a.last("state").seq, 0);
  assert.equal(b.last("state").seq, 0);
});

test("隠し情報: 各席の view に、相手の手札は入らない(state にも events にも)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  const [ha, hb] = [handOf(a), handOf(b)];
  const raw = JSON.stringify(a.out);
  assert.ok(!("hands" in a.last("state").view));
  assert.equal(a.last("state").view.oppCount, 3);
  assert.deepEqual(a.last("state").view.hand, ha);
  assert.deepEqual(b.last("state").view.hand, hb);
  assert.ok(!raw.includes('"hands"'));
});

test("act: 正しい手は、全員に state(seq+1・その席の view)が届く", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  const n = handOf(a)[0];
  env.say(a, { t: "act", a: { type: "play", n } });
  assert.equal(a.last("state").seq, 1);
  assert.equal(b.last("state").seq, 1);
  assert.deepEqual(a.last("state").events, [{ t: "played", seat: 0, n }]);
  assert.equal(handOf(a).length, 2);
  assert.equal(b.last("state").view.oppCount, 2);   // b から見た相手(a)は、手札が3→2
  assert.equal(b.last("state").view.played[0].length, 1);
});

test("act: ルール違反は、本人に error(rule)+最新の state(resync)だけ。他の席には何も送らない。状態は変わらない", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  const before = b.out.length;
  env.say(a, { t: "act", a: { type: "play", n: 99 } });
  const e = a.last("error");
  assert.deepEqual([e.code, e.d], ["rule", "no-card"]);
  const st = a.last("state");
  assert.equal(st.resync, true);
  assert.equal(st.seq, 0);
  assert.equal(b.out.length, before);
  env.say(a, { t: "act", a: { type: "nope" } });            // 例外にならない手も同じ
  assert.equal(a.last("error").d, "bad-action");
  assert.equal(a.last("state").seq, 0);
});

test("act: 形の悪い入力・大きすぎる手は捨てる(落ちない)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  env.say(a, { t: "act" });
  assert.equal(a.last("error").code, "rate");
  env.say(a, { t: "act", a: { type: "play", n: 1, pad: "x".repeat(5000) } });
  assert.equal(a.last("error").code, "rate");
  assert.equal(b.last("state").seq, 0);
});

test("act: apply が例外を投げても、状態は壊れない(error rule + resync)", () => {
  const boom = { ...cards, id: "boom", game: { ...cards.game, apply: () => { throw new Error("x"); } } };
  const env = setup({ boom });
  const [a, b] = pair(env, "boom");
  env.say(a, { t: "act", a: { type: "play", n: 1 } });
  assert.deepEqual([a.last("error").code, a.last("error").d], ["rule", "exception"]);
  assert.equal(a.last("state").resync, true);
  assert.equal(b.last("state").seq, 0);
});

test("resync: 自分の最新の view を、自分だけに送り直す", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  const nb = b.out.length;
  env.say(a, { t: "resync" });
  assert.equal(a.last("state").resync, true);
  assert.deepEqual(a.last("state").view.hand, handOf(a));
  assert.equal(b.out.length, nb);
});

test("outcome(rematch: game): 終わったとき result を1回だけ送る。部屋は playing のまま、ゲームの手で次へ", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  for (const w of [a, b]) for (const n of [...handOf(w)]) env.say(w, { t: "act", a: { type: "play", n } });
  assert.equal(a.all("result").length, 1);
  assert.equal(b.all("result").length, 1);
  const rank = a.last("result").ranks;
  assert.equal(rank.length, 2);
  assert.equal(a.last("result").why, "normal");
  // 終わったあとも act を受ける(結果を表示したあと、ゲーム内の「もう一度」)
  env.say(a, { t: "act", a: { type: "again" } });
  assert.equal(handOf(a).length, 3);
  assert.equal(a.all("result").length, 1);                  // 続く間は、送り直さない
  for (const w of [a, b]) for (const n of [...handOf(w)]) env.say(w, { t: "act", a: { type: "play", n } });
  assert.equal(a.all("result").length, 2);                  // 次に終わったとき、また1回
});

test("outcome(rematch: framework): result のあと over。act は無視され、全員 rematch で新しい対戦", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "framed");
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  for (const w of [a, b]) for (const n of [...handOf(w)]) env.say(w, { t: "act", a: { type: "play", n } });
  assert.equal(a.all("result").length, 1);
  const n = a.out.length;
  env.say(a, { t: "act", a: { type: "again" } });           // over では受けない
  assert.equal(a.out.length, n);
  assert.equal(env.store.has([...env.store.keys()].find((k) => k.startsWith("room:")).replace("room:", "state:")), false);   // 状態は消える
  env.say(a, { t: "rematch" }); env.say(b, { t: "rematch" });
  assert.equal(a.all("match").length, 2);
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  assert.equal(a.last("state").seq, 0);
  assert.equal(handOf(a).length, 3);
});

test("rematch: game のゲームでは、rematch メッセージは何もしない", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  for (const w of [a, b]) for (const n of [...handOf(w)]) env.say(w, { t: "act", a: { type: "play", n } });
  env.say(a, { t: "rematch" }); env.say(b, { t: "rematch" });
  assert.equal(a.all("match").length, 1);
});

test("休止: 状態と乱数の位置は kv にあるので、核を作り直しても続きが同じ(乱数も途切れない)", () => {
  const run = (swap) => {
    const env = setup(GAMES, { random: (() => { let x = 7; return () => ((x = (x * 16807) % 2147483647) / 2147483647); })() });
    const [a, b] = pair(env, "cards");
    let core = env.core;
    for (let i = 0; i < 4; i++) {
      if (swap) core = new NetGameCore(env.core.host, GAMES);     // Durable Object が休止して起きた = 新しい核
      core.onMessage(i % 2 ? b : a, JSON.stringify({ t: "act", a: { type: "draw" } }));
    }
    return a.last("state").view.draws;
  };
  const straight = run(false);
  assert.equal(straight.length, 4);
  assert.equal(new Set(straight).size, 4);                          // 同じ値を繰り返さない(乱数の位置が保たれている)
  assert.deepEqual(run(true), straight);
});

test("退出: 対戦中に leave すると、すぐ残りの人の勝ち(why: left)。状態は消える", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  env.say(a, { t: "leave" });
  assert.deepEqual(b.last("result").ranks, [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }]);
  assert.equal(b.last("result").why, "left");
  assert.equal([...env.store.keys()].some((k) => k.startsWith("state:")), false);
});

test("event(スタンプ): authoritative でも turns でも、アダプターの events があれば中継できる", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  env.say(a, { t: "event", k: "stamp", d: { id: 2 } });
  assert.deepEqual(b.last("event"), { t: "event", seat: 0, k: "stamp", d: { id: 2 } });
  env.say(a, { t: "event", k: "stamp", d: { id: 99 } });           // 形が悪い
  assert.equal(b.all("event").length, 1);
  const [c, d] = pair(env, "tstamp");
  env.say(c, { t: "ready" }); env.say(d, { t: "ready" });
  env.say(c, { t: "event", k: "stamp", d: {} });
  assert.equal(d.all("event").length, 1);
});

test("部屋コード(alnum4・パスワードなし): 4文字の英数。小文字で入っても同じ部屋。パスワードは送らなくてよい", () => {
  const env = setup(GAMES);
  const a = env.open("cards", V2); const b = env.open("cards", V2);
  env.say(a, { t: "register", name: "あ", mode: "friend", settings: {} });
  const code = a.last("waiting").room;
  assert.match(code, /^[A-HJ-NP-Z2-9]{4}$/);
  env.say(b, { t: "register", name: "い", mode: "friend", room: code.toLowerCase() });
  assert.equal(a.last("match").you, 0);
  assert.equal(b.last("match").you, 1);
  assert.equal(b.all("start").length, 1);
});

test("部屋コード(optional): パスワードありの部屋は、合っていないと入れない。なしの部屋は、なしで入れる", () => {
  const env = setup(GAMES);
  const a = env.open("optpass", V2);
  env.say(a, { t: "register", name: "あ", mode: "friend", pass: "1234" });
  const code = a.last("waiting").room;
  const b = env.open("optpass", V2);
  env.say(b, { t: "register", name: "い", mode: "friend", room: code });
  assert.equal(b.last("error").code, "pass");
  env.say(b, { t: "register", name: "い", mode: "friend", room: code, pass: "1234" });
  assert.equal(b.last("match").you, 1);
  const c = env.open("optpass", V2);
  env.say(c, { t: "register", name: "う", mode: "friend", pass: "12" });          // 形が悪いパスワード
  assert.equal(c.last("error").code, "key");
  env.say(c, { t: "register", name: "う", mode: "friend" });                       // パスワードなしの部屋
  const code2 = c.last("waiting").room;
  const d = env.open("optpass", V2);
  env.say(d, { t: "register", name: "え", mode: "friend", room: code2 });
  assert.equal(d.last("match").you, 1);
});

test("入室失敗の制限: 5回失敗すると60秒入れない(retry_ms)。時間が過ぎれば入れる。成功で数え直し", () => {
  const env = setup(GAMES);
  const a = env.open("cards", V2);
  env.say(a, { t: "register", name: "あ", mode: "friend" });
  const code = a.last("waiting").room;
  const x = env.open("cards", { ...V2, clientKey: "1.1.1.1" });
  const tryJoin = (w, room) => env.say(w, { t: "register", name: "ぬ", mode: "friend", room });
  for (let i = 0; i < 5; i++) { tryJoin(x, "ZZZZ"); assert.equal(x.last("error").code, "room"); }
  tryJoin(x, code);                                                  // 正しいコードでも、入れない時間のあいだは断る
  assert.equal(x.last("error").code, "rate");
  assert.ok(x.last("error").d.retry_ms > 0 && x.last("error").d.retry_ms <= 60000);
  // 接続し直しても、同じ接続元なら続く(別の接続元は影響を受けない)
  const x2 = env.open("cards", { ...V2, clientKey: "1.1.1.1" });
  tryJoin(x2, code);
  assert.equal(x2.last("error").code, "rate");
  const y = env.open("cards", { ...V2, clientKey: "2.2.2.2" });
  tryJoin(y, "ZZZZ");
  assert.equal(y.last("error").code, "room");
  env.tick(60001);
  tryJoin(x2, code);
  assert.equal(x2.last("match").you, 1);
  assert.equal([...env.store.keys()].some((k) => k.startsWith("jf:1.1.1.1")), false);    // 成功したら、記録は消える
});

test("入室失敗の制限: 接続元が分からないときは、接続ごとに数える。v1 の既定(パスワード必須)では制限を足さない", () => {
  const env = setup(GAMES);
  const x = env.open("cards", V2);
  for (let i = 0; i < 5; i++) env.say(x, { t: "register", name: "ぬ", mode: "friend", room: "ZZZZ" });
  env.say(x, { t: "register", name: "ぬ", mode: "friend", room: "ZZZZ" });
  assert.equal(x.last("error").code, "rate");
  const f = env.open("framed", V2);                                 // password: required は、部屋ごとの制限(passFails)だけ
  for (let i = 0; i < 8; i++) env.say(f, { t: "register", name: "ぬ", mode: "friend", pass: "1234", room: "123456" });
  assert.equal(f.last("error").code, "room");
});

test("設定の正規化・ランダムマッチ・チャットは、authoritative でも同じ", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  env.say(a, { t: "chat", text: "こんにちは" });
  assert.equal(b.last("chat").text, "こんにちは");
});

test("保存の量: 1手の書き込みは1行(状態だけ)。断られた手・resync・チャットは書かない", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  const writes = [];
  const kv = env.core.host.kv;
  const { put, delete: del } = kv;
  kv.put = (k, v) => { writes.push("put " + k.split(":")[0]); put(k, v); };
  kv.delete = (k) => { writes.push("del " + k.split(":")[0]); del(k); };
  const n = handOf(a)[0];
  env.say(a, { t: "act", a: { type: "play", n } });
  assert.deepEqual(writes, ["put state"]);
  writes.length = 0;
  env.say(a, { t: "act", a: { type: "play", n: 99 } });          // 断られた手
  env.say(a, { t: "resync" });
  env.say(b, { t: "chat", text: "やあ" });
  env.say(b, { t: "event", k: "stamp", d: { id: 1 } });
  assert.deepEqual(writes, []);
  // 結果が出た手だけは、部屋の記録(result)も書く
  for (const w of [a, b]) for (const m of [...handOf(w)]) env.say(w, { t: "act", a: { type: "play", n: m } });
  assert.ok(writes.filter((x) => x === "put room").length <= 1);
});

test("seq・乱数の位置・通知済みフラグは、状態といっしょに保存される(核を作り直しても、結果は1回だけ・seq は続く)", () => {
  const env = setup(GAMES);
  const [a, b] = pair(env, "cards");
  env.say(a, { t: "act", a: { type: "draw" } });
  const fresh = new NetGameCore(env.core.host, GAMES);
  fresh.onMessage(b, JSON.stringify({ t: "act", a: { type: "draw" } }));
  assert.equal(a.last("state").seq, 2);
  assert.equal(a.last("state").view.draws.length, 2);
  for (const w of [a, b]) for (const m of [...handOf(w)]) new NetGameCore(env.core.host, GAMES).onMessage(w, JSON.stringify({ t: "act", a: { type: "play", n: m } }));
  assert.equal(a.all("result").length, 1);
  new NetGameCore(env.core.host, GAMES).onMessage(a, JSON.stringify({ t: "act", a: { type: "draw" } }));   // 終わったあとの手でも、結果は送り直さない
  assert.equal(a.all("result").length, 1);
});

test("入室失敗の記録: 最後の失敗から1時間たったら数え直し。期限を過ぎた記録は、戻ってこなくても消える", () => {
  const env = setup(GAMES);
  const fail = (key) => { const w = env.open("cards", { ...V2, clientKey: key }); env.say(w, { t: "register", name: "ぬ", mode: "friend", room: "ZZZZ" }); return w; };
  // 4回失敗 → 1時間+1ms → また4回: 合計8回でも、ブロックされない(数え直されるので)
  for (let i = 0; i < 4; i++) fail("aaaa");
  env.tick(3600001);
  let last;
  for (let i = 0; i < 4; i++) last = fail("aaaa");
  assert.equal(last.last("error").code, "room");
  // 期限を過ぎた記録は、ほかの接続元の失敗のときに、一緒に消える(戻ってこない接続元の記録が、残り続けない)
  fail("bbbb");
  env.tick(3600001);
  fail("cccc");
  const keys = [...env.store.keys()].filter((k) => k.startsWith("jf:"));
  assert.deepEqual(keys, ["jf:cccc"]);
  assert.deepEqual(JSON.parse(env.store.get("jfq")).map(([k]) => k), ["jf:cccc"]);
  // 1時間のうちなら、続けて数える(5回でブロック)
  const blocked = (() => { let w; for (let i = 0; i < 5; i++) w = fail("dddd"); env.tick(1000); return fail("dddd"); })();
  assert.equal(blocked.last("error").code, "rate");
});

test("hashClientKey: 生の接続元を含まない16桁の16進。同じ入力なら同じ、接続元や salt が違えば違う。接続元がなければ undefined", async () => {
  const a = await hashClientKey("203.0.113.7", "salt-1");
  assert.match(a, /^[0-9a-f]{16}$/);
  assert.equal(a, await hashClientKey("203.0.113.7", "salt-1"));
  assert.notEqual(a, await hashClientKey("203.0.113.8", "salt-1"));
  assert.notEqual(a, await hashClientKey("203.0.113.7", "salt-2"));
  assert.equal(await hashClientKey(null, "salt-1"), undefined);
  assert.equal(await hashClientKey("", "salt-1"), undefined);
});
