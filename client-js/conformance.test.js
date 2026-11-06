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

/** 再接続の待ち時間を、テストが決めた時に発火させるための時計(setTimeout の代わり) */
function manualTimer() {
  const pending = new Set();
  return {
    set: (fn) => { const h = { fn }; pending.add(h); return h; },
    clear: (h) => pending.delete(h),
    now: () => 0,
    fire() { for (const h of [...pending]) { pending.delete(h); h.fn(); } },
  };
}

export async function runScenario() {
  const world = makeWorld();
  const WS = coreSocketClass(world);
  const clients = new Map();
  const timers = new Map();
  const stores = new Map();             // 保存先(token と部屋コード)。connect の storage で、同じものを共有する(ページを開き直した想定)
  const storageFor = (name) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const m = stores.get(name);
    return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
  };
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
        const timer = manualTimer();
        const n = new NetGameClient({ url: "ws://world/ws", game: scenario.game, v: scenario.v, WebSocket: WS, timer, storage: storageFor(s.storage ?? s.who) });
        clients.set(s.who, n); timers.set(s.who, timer); live.add(s.who);
        await n.connect();
        break;
      }
      case "registerRandom": assert.equal(c.registerRandom({ name: s.name }), s.expect ?? true); break;
      case "registerFriend":
        assert.equal(c.registerFriend({ name: s.name, pass: s.pass, room: s.room?.startsWith("$room:") ? clients.get(s.room.split(":")[1]).room : s.room }), s.expect ?? true);
        break;
      case "act": assert.ok(c.act(resolve(s.who, s.a))); break;
      case "event": c.event(s.k, s.d); break;
      case "chat": c.say(s.text); break;
      case "drop": c.close(); live.delete(s.who); break;
      case "netDrop": c._ws._drop(); break;                           // 通信が途切れた(自動再接続の待ちに入る)
      case "awaitReconnect":
        assert.equal(c.status, "reconnecting");
        timers.get(s.who).fire();
        for (let k = 0; k < 50 && !(c.status === "open" && !["resuming", "connecting"].includes(c.phase)); k++) await settle(clients);
        break;
      case "resumeSaved": assert.ok(c.resume()); break;
      case "leave": c.leave(); break;
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
