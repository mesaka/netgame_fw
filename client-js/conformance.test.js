// 適合テスト(JS 側): シナリオ(tests/conformance/scenario.json)を JS クライアントで実行し、各ステップの snapshot() が
// golden.json と一致することを確かめる。Python 側(tests/test_conformance.py)も、同じ golden と比べる = 2つのクライアントが同じ解釈をする。
// golden を作り直すとき: UPDATE_GOLDEN=1 npm test
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { NetGameClient } from "./netgame/client.js";
import { makeWorld, coreSocketClass } from "../tests/conformance/world.mjs";

const DIR = new URL("../tests/conformance/", import.meta.url);
const scenario = JSON.parse(readFileSync(new URL("scenario.json", DIR), "utf8"));
const GOLDEN = new URL("golden.json", DIR);

const settle = async (clients) => {
  for (let i = 0; i < 3; i++) {
    await Promise.all([...clients.values()].map((c) => c.idle()));
    await new Promise((r) => setImmediate(r));
  }
};

export async function runScenario() {
  const world = makeWorld();
  const WS = coreSocketClass(world);
  const clients = new Map();
  const live = new Set();
  const resolve = (who, v) => {
    if (typeof v === "string" && v === "$hand0") return clients.get(who).view.hand[0];
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, resolve(who, x)]));
    return v;
  };
  const log = [];
  for (const [i, s] of scenario.steps.entries()) {
    const c = clients.get(s.who);
    switch (s.do) {
      case "connect": {
        const n = new NetGameClient({ url: "ws://world/ws", game: scenario.game, v: scenario.v, WebSocket: WS, reconnect: false });
        clients.set(s.who, n); live.add(s.who);
        await n.connect();
        break;
      }
      case "registerRandom": c.registerRandom({ name: s.name }); break;
      case "registerFriend": c.registerFriend({ name: s.name, room: s.room ? clients.get(s.room.split(":")[1]).room : undefined }); break;
      case "act": c.act(resolve(s.who, s.a)); break;
      case "event": c.event(s.k, s.d); break;
      case "chat": c.say(s.text); break;
      case "drop": c.close(); live.delete(s.who); break;
      case "resume": { const f = clients.get(s.from); c.resume({ room: f.room, token: f.token }); break; }
      case "playAll":
        for (const n of [...c.view.hand]) { c.act({ type: "play", n }); await settle(clients); }
        break;
      case "tick": world.tick(s.ms); break;
      case "alarm": world.alarm(); break;
      default: throw new Error("知らない手順: " + s.do);
    }
    await settle(clients);
    log.push({ step: i, snaps: Object.fromEntries([...live].map((w) => [w, clients.get(w).snapshot()])) });
  }
  return log;
}

test("適合(JS): シナリオの各ステップのあとの snapshot が golden と一致する", async () => {
  const log = await runScenario();
  if (process.env.UPDATE_GOLDEN) { writeFileSync(GOLDEN, JSON.stringify(log, null, 1) + "\n"); return; }
  const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));
  assert.equal(log.length, golden.length);
  for (const [i, g] of golden.entries()) {
    assert.deepEqual(JSON.parse(JSON.stringify(log[i])), g, `step ${i}: ${JSON.stringify(scenario.steps[i])}`);
  }
});
