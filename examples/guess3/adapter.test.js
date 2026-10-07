// 数当て(3人・turns)の確認。N人の部屋の、席・名簿・準備OK・手番の巡り・ハッシュの突き合わせ・結果の一致・退出。
import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "../../server/testkit.js";
import guess3 from "./adapter.js";

const mk = () => setup({ guess3 });

function start(env) {
  const ws = [env.open("guess3"), env.open("guess3"), env.open("guess3")];
  ws.forEach((w, i) => env.say(w, { t: "register", name: "なまえ" + i, mode: "random" }));
  return ws;
}
const ready = (env, ws) => ws.forEach((w) => env.say(w, { t: "ready" }));

test("3人そろうまで始まらない。席は待った順で、名簿は3人分", () => {
  const env = mk();
  const a = env.open("guess3"); const b = env.open("guess3");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  assert.equal(a.last("match"), undefined);
  assert.equal(a.last("waiting").t, "waiting");
  const c = env.open("guess3");
  env.say(c, { t: "register", name: "う", mode: "random" });
  for (const [i, w] of [a, b, c].entries()) {
    const m = w.last("match");
    assert.equal(m.you, i);
    assert.deepEqual(m.players.map((p) => p.name), ["あ", "い", "う"]);
    assert.equal(m.mode, "turns");
  }
});

test("準備OK: 押した席の一覧が全員に届き、3人そろったら start(最初の手番つき)", () => {
  const env = mk();
  const ws = start(env);
  env.say(ws[1], { t: "ready" });
  assert.deepEqual(ws[0].last("ready_state").seats, [1]);
  env.say(ws[2], { t: "ready" });
  assert.equal(ws[0].last("start"), undefined);
  env.say(ws[0], { t: "ready" });
  for (const w of ws) assert.deepEqual(w.last("start").turn, { seat: 0, seq: 0 });
});

test("手番は席の順に巡る(0 → 1 → 2 → 0)。本人にも返る。手番でない人の手・形の違う手は捨てる", () => {
  const env = mk();
  const ws = start(env); ready(env, ws);
  env.say(ws[1], { t: "action", seq: 0, d: { n: 10 } });
  assert.equal(ws[1].last("error").code, "state");
  env.say(ws[0], { t: "action", seq: 0, d: { n: 500 } });          // 範囲外
  assert.equal(ws[0].last("error").code, "rule");
  env.say(ws[0], { t: "action", seq: 0, d: { n: 50 } });
  for (const w of ws) {
    assert.deepEqual(w.last("action"), { t: "action", seat: 0, seq: 0, d: { n: 50 } });
    assert.deepEqual(w.last("turn"), { t: "turn", seat: 1, seq: 1 });
  }
  env.say(ws[1], { t: "action", seq: 1, d: { n: 20 } });
  assert.deepEqual(ws[2].last("turn"), { t: "turn", seat: 2, seq: 2 });
  env.say(ws[2], { t: "action", seq: 2, d: { n: 70 } });
  assert.deepEqual(ws[0].last("turn"), { t: "turn", seat: 0, seq: 3 });
});

function playRound(env, ws) {
  [50, 20, 70].forEach((n, i) => env.say(ws[i], { t: "action", seq: i, d: { n } }));
}

test("ハッシュ: 3人全員が一致すれば何も起きない。1人でも違えば desync で中止", () => {
  const env = mk();
  const ws = start(env); ready(env, ws); playRound(env, ws);
  ws.forEach((w) => env.say(w, { t: "sync", seq: 0, h: "same" }));
  assert.equal(ws[0].last("desync"), undefined);
  env.say(ws[0], { t: "sync", seq: 1, h: "x" });
  env.say(ws[1], { t: "sync", seq: 1, h: "x" });
  assert.equal(ws[0].last("desync"), undefined, "3人目を待つ");
  env.say(ws[2], { t: "sync", seq: 1, h: "y" });
  for (const w of ws) {
    assert.equal(w.last("desync").seq, 1);
    assert.equal(w.last("result").why, "desync");
  }
});

test("結果: 全員の finish が一致したら確定(3人の順位・同順位あり)。食い違えば desync", () => {
  const env = mk();
  const ws = start(env); ready(env, ws); playRound(env, ws);
  const ranks = [{ seat: 0, rank: 1 }, { seat: 1, rank: 3 }, { seat: 2, rank: 1 }];
  env.say(ws[0], { t: "finish", ranks });
  env.say(ws[1], { t: "finish", ranks: [...ranks].reverse() });     // 並びが違っても、同じ内容なら一致
  assert.equal(ws[0].last("result"), undefined);
  env.say(ws[2], { t: "finish", ranks });
  for (const w of ws) {
    const r = w.last("result");
    assert.equal(r.why, "normal");
    assert.deepEqual(r.ranks.map((x) => x.rank), [1, 3, 1]);
  }
  const env2 = mk();
  const w2 = start(env2); ready(env2, w2);
  env2.say(w2[0], { t: "finish", ranks });
  env2.say(w2[1], { t: "finish", ranks });
  env2.say(w2[2], { t: "finish", ranks: [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }, { seat: 2, rank: 3 }] });
  assert.equal(w2[0].last("result").why, "desync");
});

test("人数に合わない順位の申告は、受け付けない", () => {
  const env = mk();
  const ws = start(env); ready(env, ws);
  env.say(ws[0], { t: "finish", ranks: [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }] });
  assert.equal(ws[0].last("error").code, "state");
});

test("対戦中に1人が抜けると、(いまは)中止。結果は why: abort で、残りの2人に届く", () => {
  const env = mk();
  const ws = start(env); ready(env, ws);
  env.close(ws[2]);
  for (const w of [ws[0], ws[1]]) {
    const r = w.last("result");
    assert.equal(r.why, "abort");
    assert.ok(r.ranks.every((x) => x.rank === 1));
  }
});

test("一時停止は、席の集合で持つ(3人のうち2人が止めても、解除は各自)", () => {
  const env = mk();
  const ws = start(env); ready(env, ws);
  env.say(ws[0], { t: "pause", on: true });
  env.say(ws[1], { t: "pause", on: true });
  assert.deepEqual([ws[2].all("paused").map((m) => [m.seat, m.on])][0], [[0, true], [1, true]]);
  env.say(ws[0], { t: "pause", on: false });
  assert.deepEqual(ws[2].last("paused"), { t: "paused", seat: 0, on: false });
});
