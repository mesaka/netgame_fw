// templates/server/ の雛形が、そのまま動くことの確認(新しいゲームは、これをコピーして書き始める)。
import test from "node:test";
import assert from "node:assert/strict";
import { setup } from "./testkit.js";
import mygame from "../templates/server/adapter.js";

test("雛形のアダプター: 同じ設定の2人が組み、イベントを中継し、lose で結果が決まる", () => {
  const env = setup({ mygame });
  const a = env.open("mygame"); const b = env.open("mygame");
  env.say(a, { t: "register", name: "あ", mode: "random", settings: { level: "hard" } });
  env.say(b, { t: "register", name: "い", mode: "random", settings: { level: "hard" } });
  assert.deepEqual(a.last("match").settings, { level: "hard" });
  env.say(a, { t: "ready" }); env.say(b, { t: "ready" });
  env.say(a, { t: "event", k: "move", d: { x: 5 } });
  assert.deepEqual(b.last("event"), { t: "event", seat: 0, k: "move", d: { x: 5 } });
  env.say(a, { t: "event", k: "move", d: { x: 500 } });             // 範囲外は捨てる
  assert.equal(b.all("event").length, 1);
  env.say(a, { t: "event", k: "lose", d: {} });
  assert.deepEqual(b.last("result").ranks, [{ seat: 0, rank: 2 }, { seat: 1, rank: 1 }]);
});

test("雛形のアダプター: 設定が違う人とは組まない", () => {
  const env = setup({ mygame });
  const a = env.open("mygame"); const b = env.open("mygame");
  env.say(a, { t: "register", name: "あ", mode: "random", settings: { level: "easy" } });
  env.say(b, { t: "register", name: "い", mode: "random", settings: { level: "hard" } });
  assert.equal(a.last("match"), undefined);
});
