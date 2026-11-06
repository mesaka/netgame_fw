// JS クライアント(client-js)を使って、本物の Workers ランタイム(wrangler dev)に、本物の WebSocket でつないで確かめる。
//   npx wrangler dev -c examples/cards/wrangler.jsonc --port 8787 &
//   node examples/cards/e2e-client.mjs [ws://localhost:8787/ws]
// 自動再接続(通信が途切れたときに、resume で同じ席に戻る)を、実際の通信で確かめる。
import { NetGameClient } from "../../client-js/netgame/client.js";

const URL_ = process.argv[2] || "ws://localhost:8787/ws";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const ok = (cond, label) => { console.log(`${cond ? "ok" : "NG"}: ${label}`); if (!cond) failed++; };
const until = async (f, ms = 8000) => { const t = Date.now(); while (!f()) { if (Date.now() - t > ms) return false; await sleep(20); } return true; };
const make = () => new NetGameClient({ url: URL_, game: "cards", v: 2, reconnect: { minMs: 200, maxMs: 500 } });

const a = make(); const b = make();
const cfg = await a.connect(); await b.connect();
ok(cfg.mode === "authoritative" && cfg.flow.ready === false, "hello の config(authoritative・ready なし)");
a.registerRandom({ name: "あ" }); b.registerRandom({ name: "い" });
ok(await until(() => a.phase === "playing" && a.view && b.phase === "playing" && b.view), "ランダムマッチで対戦が始まり、state が届く");
ok(a.view.hand.length === 3 && !JSON.stringify(a.view).includes('"hands"'), "view に相手の手札は入らない");

// 手を指す
const mine = [...a.view.hand];
a.act({ type: "play", n: mine[0] });
ok(await until(() => a.seq === 1 && b.seq === 1), "手が双方に届く(seq 1)");

// 通信が途切れる(クライアントからソケットだけを落とす)→ 自動で再接続して、同じ席に戻る
const statuses = []; a.on("status", (s) => statuses.push(s));
const presence = []; b.on("presence", (m) => presence.push(m.online));
a._ws.close();
ok(await until(() => a.status === "open" && a.phase === "playing" && a.resync === true), "自動で再接続し、resume で同じ席に戻る");
ok(statuses.join(",") === "reconnecting,open", "status: reconnecting → open (" + statuses.join(",") + ")");
ok(JSON.stringify(a.view.hand) === JSON.stringify(mine.slice(1)), "手札は、切れる前のまま(出した1枚を除く)");
ok(await until(() => presence.join(",") === "false,true"), "相手に presence: offline → online (" + presence.join(",") + ")");
a.act({ type: "play", n: a.view.hand[0] });
ok(await until(() => b.seq === 2), "戻ったあとも手が指せる");

// 保存した token で、別のクライアント(ページを開き直した想定)が戻る
const store = new Map();
const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
const c = new NetGameClient({ url: URL_, game: "cards", v: 2, storage, reconnect: false });
const d = make();
await c.connect(); await d.connect();
c.registerRandom({ name: "う" }); d.registerRandom({ name: "え" });
await until(() => c.view && d.view);
const hand = [...c.view.hand];
c.close();
const c2 = new NetGameClient({ url: URL_, game: "cards", v: 2, storage, reconnect: false });
await c2.connect();
c2.resume();
ok(await until(() => c2.phase === "playing" && c2.view), "保存した token で、新しいクライアントが戻れる");
ok(JSON.stringify(c2.view.hand) === JSON.stringify(hand), "手札が同じ");

// 猶予切れ(アラーム)のあとは戻れない
c2.close();
await sleep(4500);
ok(d.result?.why === "left", "猶予(3秒)が切れたら、相手の勝ち");
const c3 = new NetGameClient({ url: URL_, game: "cards", v: 2, storage, reconnect: false });
await c3.connect();
const failedCodes = []; c3.on("resume_failed", (m) => failedCodes.push(m.code));
c3.resume();
ok(await until(() => failedCodes.length === 1) && c3.savedSession() === null, "猶予切れのあとは resume_failed。保存した token は消える");

for (const x of [a, b, c, c2, c3, d]) x.close();
console.log(failed ? `失敗: ${failed}` : "すべて ok");
process.exit(failed ? 1 : 0);
