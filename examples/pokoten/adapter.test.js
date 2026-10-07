// ポコテンのアダプター(examples/pokoten/adapter.js)の確認。
// mesaka/pokoten の、これまでのサーバーのテスト(server/lobby_core.test.js)と同じ内容を、v1 の通信で確かめる。
import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "../../server/testkit.js";
import pokoten from "./adapter.js";

const mk = () => setup({ pokoten });
const board = ".".repeat(144);

function pair(env, diff = "normal") {
  const a = env.open("pokoten"); const b = env.open("pokoten");
  env.say(a, { t: "register", name: "あ", mode: "random", settings: { diff } });
  env.say(b, { t: "register", name: "い", mode: "random", settings: { diff } });
  return [a, b];
}
function start(env, diff) {
  const [a, b] = pair(env, diff);
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  return [a, b];
}

test("むずかしさが同じ人どうしだけが組まれる。範囲外・未指定は normal", () => {
  const env = mk();
  const a = env.open("pokoten"); const b = env.open("pokoten"); const c = env.open("pokoten");
  env.say(a, { t: "register", name: "a", mode: "random", settings: { diff: "easy" } });
  env.say(b, { t: "register", name: "b", mode: "random", settings: { diff: "hard" } });
  assert.equal(a.last("match"), undefined);
  assert.equal(b.last("match"), undefined);
  env.say(c, { t: "register", name: "c", mode: "random", settings: { diff: "extreme" } });   // normal 扱い
  assert.equal(c.last("match"), undefined);
  const d = env.open("pokoten");
  env.say(d, { t: "register", name: "d", mode: "random" });                                  // 未指定も normal
  assert.deepEqual(d.last("match").settings, { diff: "normal" });
  assert.deepEqual(c.last("match").players.map((p) => p.name), ["c", "d"]);
});

test("名前を登録して、2人目で対戦が始まる(待っていた人が 0 番、同じ seed)", () => {
  const env = mk();
  const [a, b] = pair(env, "hard");
  assert.deepEqual([a.last("match").you, b.last("match").you], [0, 1]);
  assert.equal(a.last("match").seed, b.last("match").seed);
  assert.deepEqual(a.last("match").settings, { diff: "hard" });
});

test("準備OK: 双方が押すまで、攻撃・盤面・負けは中継しない", () => {
  const env = mk();
  const [a, b] = pair(env);
  env.say(a, { t: "event", k: "attack", d: { n: 1 } });
  env.say(a, { t: "event", k: "snap", d: { b: board, sc: 1, g: 0 } });
  env.say(a, { t: "event", k: "over", d: {} });
  assert.equal(b.last("event"), undefined);
  assert.equal(b.last("result"), undefined);
  env.say(a, { t: "ready" });
  assert.ok(b.last("ready_state"));
  env.say(b, { t: "ready" });
  assert.ok(a.last("start") && b.last("start"));
});

test("消去(attack)は相手へのおじゃまとして届く。自分には届かず、範囲外は捨てる", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "event", k: "attack", d: { n: 1 } });
  assert.deepEqual(b.last("event"), { t: "event", seat: 0, k: "attack", d: { n: 1 } });
  assert.equal(a.last("event"), undefined);
  env.say(a, { t: "event", k: "attack", d: { n: 999 } });
  env.say(a, { t: "event", k: "attack", d: { n: 0 } });
  env.say(a, { t: "event", k: "attack", d: { n: "1" } });
  assert.equal(b.all("event").length, 1);
});

test("盤面(snap)は形式が正しいものだけ中継する", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "event", k: "snap", d: { b: board, sc: 120, g: 2 } });
  assert.deepEqual(b.last("event").d, { b: board, sc: 120, g: 2 });
  env.say(a, { t: "event", k: "snap", d: { b: "x".repeat(144), sc: 1, g: 0 } });
  env.say(a, { t: "event", k: "snap", d: { b: ".".repeat(10), sc: 1, g: 0 } });
  env.say(a, { t: "event", k: "snap", d: { b: board, sc: -1, g: 0 } });
  env.say(a, { t: "event", k: "snap", d: { b: board, sc: 1 } });
  assert.equal(b.all("event").length, 1);
});

test("負け(over)で勝敗が決まる。二重には決まらず、そのあとの attack は届かない", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "event", k: "over", d: {} });
  assert.deepEqual(a.last("result").ranks, [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }]);
  assert.deepEqual(b.last("result").ranks, a.last("result").ranks);
  env.say(b, { t: "event", k: "attack", d: { n: 1 } });
  assert.equal(a.last("event"), undefined);
  env.say(b, { t: "event", k: "over", d: {} });
  assert.equal(b.all("result").length, 1);
});

test("もう一度: 両者が押したら新しい seed。準備OKからやり直し", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "event", k: "over", d: {} });
  env.say(a, { t: "rematch" });
  assert.equal(b.last("rematch_req").seat, 0);
  env.say(b, { t: "rematch" });
  assert.equal(a.all("match").length, 2);
  assert.equal(a.all("match")[1].seed, b.all("match")[1].seed);
  env.say(b, { t: "event", k: "attack", d: { n: 1 } });
  assert.equal(a.last("event"), undefined);
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  env.say(b, { t: "event", k: "attack", d: { n: 1 } });
  assert.ok(a.last("event"));
});

test("対戦中に相手が切れたら勝ち。終了後に切れたら player_left", () => {
  const env = mk();
  let [a, b] = start(env);
  env.close(a);
  assert.equal(b.last("result").why, "left");
  assert.deepEqual(b.last("result").ranks, [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }]);
  [a, b] = start(env);
  env.say(a, { t: "event", k: "over", d: {} });
  env.close(a);
  assert.deepEqual(b.last("player_left"), { t: "player_left", seat: 0 });
});

test("チャットは両者に届き、30文字で切られ、連投は止められる", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "chat", text: "あ".repeat(50) });
  assert.equal(b.last("chat").text.length, 30);
  assert.equal(a.last("chat").name, "あ");
  env.say(a, { t: "chat", text: "すぐ" });
  assert.equal(b.all("chat").length, 1);
  env.tick(500);
  env.say(a, { t: "chat", text: "あとで" });
  assert.equal(b.all("chat").length, 2);
});

test("ルーム: ルームID+パスワードで組まれる。むずかしさは作った人のもの。準備OK→対戦", () => {
  const env = mk();
  const host = env.open("pokoten");
  env.say(host, { t: "register", name: "ホスト", mode: "friend", pass: "1234", settings: { diff: "hard" } });
  const room = host.last("waiting").room;
  const guest = env.open("pokoten");
  env.say(guest, { t: "register", name: "ゲスト", mode: "friend", room, pass: "1234", settings: { diff: "easy" } });
  assert.deepEqual(guest.last("match").settings, { diff: "hard" });
  env.say(host, { t: "ready" }); env.say(guest, { t: "ready" });
  env.say(guest, { t: "event", k: "attack", d: { n: 2 } });
  assert.equal(host.last("event").d.n, 2);
});

test("ルーム: パスワード違い・ルームなし・5回間違えで閉じる", () => {
  const env = mk();
  const host = env.open("pokoten");
  env.say(host, { t: "register", name: "h", mode: "friend", pass: "1234" });
  const room = host.last("waiting").room;
  const g = env.open("pokoten");
  env.say(g, { t: "register", name: "g", mode: "friend", room: "999999", pass: "1234" });
  assert.equal(g.last("error").code, "room");
  for (let i = 0; i < 5; i++) {
    env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "000" + i });
    assert.equal(g.last("error").code, "pass");
  }
  env.say(g, { t: "register", name: "g", mode: "friend", room, pass: "1234" });
  assert.equal(g.last("error").code, "room");
});

test("一時停止: 止めた席を相手へ中継する", () => {
  const env = mk();
  const [a, b] = start(env);
  env.say(a, { t: "pause", on: true });
  assert.deepEqual(b.last("paused"), { t: "paused", seat: 0, on: true });
  env.say(a, { t: "pause", on: false });
  assert.equal(b.last("paused").on, false);
});
