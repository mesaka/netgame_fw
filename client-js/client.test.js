// JS クライアントの単体テスト(世界 = サーバーの核を、同じプロセスの中で動かす)。再接続・保存・順序など。
import test from "node:test";
import assert from "node:assert/strict";
import { NetGameClient, cleanText } from "./netgame/client.js";
import { cleanText as serverCleanText } from "../server/text.js";
import { makeWorld, coreSocketClass } from "../tests/conformance/world.mjs";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (f, ms = 2000) => { const t = Date.now(); while (!f()) { if (Date.now() - t > ms) throw new Error("時間切れ"); await sleep(2); } };
const FAST = { minMs: 5, maxMs: 20, giveUpMs: 5000 };

function env({ reconnect = FAST } = {}) {
  const world = makeWorld();
  const WS = coreSocketClass(world);
  const store = new Map();
  const storage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
  const make = (extra = {}) => new NetGameClient({ url: "ws://world/ws", game: "cards", v: 2, WebSocket: WS, reconnect, storage, ...extra });
  const pair = async () => {
    const a = make({ storage: null }); const b = make({ storage: null });
    await a.connect(); await b.connect();
    a.registerRandom({ name: "あ" }); b.registerRandom({ name: "い" });
    await until(() => a.phase === "playing" && b.phase === "playing" && a.view && b.view);
    return [a, b];
  };
  return { world, WS, store, storage, make, pair };
}

test("接続: hello の config が届く。v1 で authoritative に入ろうとすると version エラーで、connect は失敗する", async () => {
  const e = env();
  const c = e.make();
  const config = await c.connect();
  assert.equal(config.mode, "authoritative");
  assert.equal(c.phase, "idle");
  assert.equal(c.status, "open");
  const old = e.make({ v: 1 });
  await assert.rejects(old.connect(), /version/);
  assert.equal(old.error, "version");
  assert.equal(old.phase, "closed");
});

test("対戦: ランダムマッチ → start → state。手を送ると、双方の view が更新される。隠し情報は届かない", async () => {
  const e = env();
  const [a, b] = await e.pair();
  assert.deepEqual([a.seat, b.seat], [0, 1]);                       // 先に待っていた人が席0
  assert.equal(a.view.hand.length, 3);
  assert.equal(a.view.oppCount, 3);
  assert.ok(!JSON.stringify(a.view).includes('"hands"'));
});

test("手: act で state が届き、断られた手は ruleErrors に残って、最新の view に戻る。スタンプが相手に届く", async () => {
  const e = env();
  const [a, b] = await e.pair();
  const n = a.view.hand[0];
  assert.ok(a.act({ type: "play", n }));
  await until(() => a.seq === 1 && b.seq === 1);
  assert.equal(b.view.played[0].length, 1);
  a.act({ type: "play", n: 99 });
  await until(() => a.ruleErrors.length === 1);
  assert.deepEqual(a.ruleErrors, ["no-card"]);
  assert.equal(a.resync, true);
  assert.equal(a.seq, 1);
  a.event("stamp", { id: 3 });
  await until(() => b.relayed.length === 1);
  assert.deepEqual(b.relayed[0], { seat: 0, k: "stamp", d: { id: 3 } });
});

test("順序: ハンドラーが Promise を返したら、完了まで次の通知を待つ(アニメーション中でも順番が入れ替わらない)", async () => {
  const e = env();
  const [a, b] = await e.pair();
  const seen = [];
  a.on("state", async ({ seq }) => { seen.push("start " + seq); await sleep(30); seen.push("end " + seq); });
  const [h0, h1] = a.view.hand;
  b.act({ type: "play", n: b.view.hand[0] });
  a.act({ type: "play", n: h0 });
  a.act({ type: "play", n: h1 });
  await until(() => a.seq === 3, 3000);
  await a.idle();
  assert.deepEqual(seen, ["start 1", "end 1", "start 2", "end 2", "start 3", "end 3"]);
});

test("自動再接続: 切れたら、resume で同じ席に戻る。相手には presence、戻ったあとも手が指せる。再接続中の送信は捨てる", async () => {
  const e = env();
  const [a, b] = await e.pair();
  const mine = [...a.view.hand];
  const statuses = [];
  a.on("status", (s) => statuses.push(s));
  const presence = [];
  b.on("presence", (m) => presence.push(m.online));
  a._ws._drop();
  await until(() => a.status === "reconnecting");
  assert.equal(a.act({ type: "play", n: mine[0] }), false);        // 再接続中は、古い盤面への操作になるので送らない
  await until(() => a.status === "open" && a.phase === "playing");
  assert.deepEqual(statuses, ["reconnecting", "open"]);
  assert.deepEqual(presence, [false, true]);
  assert.deepEqual(a.view.hand, mine);                              // 手札は元のまま(resync で受け取った)
  assert.equal(a.resync, true);
  assert.ok(a.act({ type: "play", n: mine[0] }));
  await until(() => b.seq === 1);
});

test("再接続できない: 猶予が切れていたら resume_failed。保存した token は消え、phase は idle(登録しなおせる)", async () => {
  const e = env({ reconnect: { minMs: 80, maxMs: 80, giveUpMs: 5000 } });
  const a = e.make(); const b = e.make({ storage: null });
  await a.connect(); await b.connect();
  a.registerRandom({ name: "あ" }); b.registerRandom({ name: "い" });
  await until(() => a.phase === "playing" && a.view);
  assert.ok(e.storage.getItem("netgame.cards"));
  const failed = [];
  a.on("resume_failed", (m) => failed.push(m.code));
  a._ws._drop();
  await until(() => a.status === "reconnecting");
  e.world.tick(61000); e.world.alarm();                             // 戻る前に、猶予が切れた
  await until(() => failed.length === 1);
  assert.deepEqual(failed, ["resume"]);
  assert.equal(a.phase, "idle");
  assert.equal(a.token, "");
  assert.equal(e.storage.getItem("netgame.cards"), null);
  assert.equal(b.result.why, "left");
});

test("保存: token と部屋コードが storage に入る。ページを開き直した想定で、新しいクライアントが resume() で戻れる。leave() で消える", async () => {
  const e = env();
  const a = e.make(); const b = e.make({ storage: null });
  await a.connect(); await b.connect();
  a.registerRandom({ name: "あ" }); b.registerRandom({ name: "い" });
  await until(() => a.phase === "playing" && a.view);
  const saved = a.savedSession();
  assert.match(saved.token, /^[0-9a-f]{32}$/);
  assert.match(saved.room, /^[A-HJ-NP-Z2-9]{4}$/);
  const hand = [...a.view.hand];
  a.close();                                                        // タブを閉じた
  const a2 = e.make();                                              // 開き直した
  await a2.connect();
  assert.ok(a2.savedSession());
  assert.ok(a2.resume());                                           // 引数なし = 保存した値
  await until(() => a2.phase === "playing" && a2.view);
  assert.deepEqual(a2.view.hand, hand);
  assert.equal(a2.seat, 0);
  a2.leave();
  assert.equal(a2.savedSession(), null);
  await until(() => b.result?.why === "left");
});

test("待機中の部屋の作成者も戻れる(部屋コードは waiting で届く)", async () => {
  const e = env();
  const h = e.make();
  await h.connect();
  h.registerFriend({ name: "あ" });
  await until(() => h.room);
  h._ws._drop();
  await until(() => h.status === "open" && h.phase === "waiting");
  const g = e.make({ storage: null });
  await g.connect();
  g.registerFriend({ name: "い", room: h.room.toLowerCase() });
  await until(() => h.phase === "playing" && g.phase === "playing");
  assert.equal(g.seat, 1);
});

test("reconnect: false なら、切れたら closed(error: lost)。close() のあとは再接続しない", async () => {
  const e = env({ reconnect: false });
  const [a] = await e.pair();
  a._ws._drop();
  await until(() => a.status === "closed");
  assert.equal(a.error, "lost");
  const e2 = env();
  const [c] = await e2.pair();
  c.close();
  await sleep(60);
  assert.equal(c.status, "closed");
  assert.equal(c.error, null);
});

test("結果: flow.rematch が game のゲームは、result のあとも playing のまま act でき、again で新しい対戦", async () => {
  const e = env();
  const [a, b] = await e.pair();
  for (const c of [a, b]) for (const n of [...c.view.hand]) { c.act({ type: "play", n }); await sleep(5); }
  await until(() => a.resultNo === 1 && b.resultNo === 1);
  assert.equal(a.phase, "playing");
  assert.equal(a.result.why, "normal");
  a.act({ type: "again" });
  await until(() => a.view.hand.length === 3);
});

test("cleanText は、サーバーの cleanText と同じ結果になる", () => {
  for (const s of ["  あ い  ", "a\u0000b​c", "x y", "😀😀😀😀😀😀😀😀😀", 5, null, "\n\t"]) {
    for (const n of [3, 8, 30]) assert.equal(cleanText(s, n), serverCleanText(s, n));
  }
});
