// ○×(2人・turns)の確認: サーバーを通した対局の流れ。ルールはクライアント側(ttt_rules.py)にあり、サーバーは手の形・手番・ハッシュ・結果の一致だけを見る。
import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "../../server/testkit.js";
import tictactoe from "./adapter.js";

const mk = () => setup({ tictactoe });

function start(env) {
  const a = env.open("tictactoe"); const b = env.open("tictactoe");
  env.say(a, { t: "register", name: "あ", mode: "random" });
  env.say(b, { t: "register", name: "い", mode: "random" });
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  return [a, b];
}

test("先手は席0。手は {cell: 0〜8} の形だけ受け付ける", () => {
  const env = mk();
  const [a, b] = start(env);
  assert.deepEqual(a.last("start").turn, { seat: 0, seq: 0 });
  for (const bad of [{ cell: 9 }, { cell: -1 }, { cell: 1.5 }, { cell: "1" }, {}, null]) {
    env.say(a, { t: "action", seq: 0, d: bad });
    assert.equal(a.last("error").code, "rule", JSON.stringify(bad));
  }
  assert.equal(b.last("action"), undefined);
  env.say(a, { t: "action", seq: 0, d: { cell: 4 } });
  assert.deepEqual(b.last("action"), { t: "action", seat: 0, seq: 0, d: { cell: 4 } });
  assert.deepEqual(a.last("turn"), { t: "turn", seat: 1, seq: 1 });
});

test("勝ちの申告: 両者が同じ結果を申告したら確定(○の勝ち)", () => {
  const env = mk();
  const [a, b] = start(env);
  const ranks = [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }];
  env.say(a, { t: "finish", ranks });
  assert.equal(b.last("result"), undefined);
  env.say(b, { t: "finish", ranks });
  for (const w of [a, b]) assert.deepEqual(w.last("result").ranks, ranks);
});

test("引き分け(両方1位)も申告できる。食い違えば desync", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "finish", ranks: [{ seat: 0, rank: 1 }, { seat: 1, rank: 1 }] });
  env.say(b, { t: "finish", ranks: [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }] });
  assert.equal(a.last("result").why, "desync");
});

test("盤面のハッシュがずれたら desync", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "action", seq: 0, d: { cell: 0 } });
  env.say(a, { t: "sync", seq: 0, h: "aaa" });
  env.say(b, { t: "sync", seq: 0, h: "bbb" });
  assert.equal(b.last("desync").seq, 0);
});

test("途中で抜けたら、残りの人の勝ち。再戦すると、また席0から", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "action", seq: 0, d: { cell: 0 } });
  env.close(b);
  assert.deepEqual(a.last("result").ranks, [{ seat: 0, rank: 1 }, { seat: 1, rank: 2 }]);
  assert.equal(a.last("result").why, "left");

  const env2 = mk();
  const [c, d] = start(env2);
  const ranks = [{ seat: 0, rank: 1 }, { seat: 1, rank: 1 }];
  env2.say(c, { t: "finish", ranks }); env2.say(d, { t: "finish", ranks });
  env2.say(c, { t: "rematch" }); env2.say(d, { t: "rematch" });
  env2.say(c, { t: "ready" }); env2.say(d, { t: "ready" });
  assert.deepEqual(c.last("start").turn, { seat: 0, seq: 0 });
});
