// 本物の Workers ランタイム(wrangler dev)に、WebSocket で2人分つないで、authoritative を通しで確かめる。
//   npx wrangler dev -c examples/cards/wrangler.jsonc --port 8787 &
//   node examples/cards/e2e.mjs [ws://localhost:8787/ws]
const URL_ = process.argv[2] || "ws://localhost:8787/ws";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const ok = (cond, label) => { console.log(`${cond ? "ok" : "NG"}: ${label}`); if (!cond) failed++; };

function client(v = 2) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`${URL_}?game=cards&v=${v}`);
    const c = { ws, out: [], last: (t) => [...c.out].reverse().find((m) => m.t === t), all: (t) => c.out.filter((m) => m.t === t),
                say: (o) => ws.send(JSON.stringify(o)) };
    ws.onmessage = (e) => c.out.push(JSON.parse(e.data));
    ws.onerror = () => reject(new Error("接続できません: " + URL_));
    ws.onopen = () => resolve(c);
  });
}

// v1 では authoritative のゲームに入れない
const old = await client(1); await sleep(300);
ok(old.last("error")?.code === "version", "v1 の接続は version エラー");

// ランダムマッチ(ready なし): すぐに start と state が届く
const a = await client(); const b = await client();
a.say({ t: "register", name: "あ", mode: "random" }); b.say({ t: "register", name: "い", mode: "random" });
await sleep(600);
ok(a.last("match") && b.last("match"), "2人が組み合わさる");
ok(a.last("state")?.seq === 0 && a.last("state").view.hand.length === 3, "start の直後に state(seq 0・手札3枚)");
ok(!JSON.stringify(a.out).includes('"hands"') && a.last("state").view.oppCount === 3, "相手の手札は届かない(枚数だけ)");

// 手を指す
const n = a.last("state").view.hand[0];
a.say({ t: "act", a: { type: "play", n } });
await sleep(300);
ok(a.last("state").seq === 1 && b.last("state").seq === 1, "手が全員に届く(seq 1)");
ok(b.last("state").view.oppCount === 2, "相手から見た枚数が減る");
a.say({ t: "act", a: { type: "play", n: 99 } });
await sleep(300);
ok(a.last("error")?.code === "rule" && a.last("state").resync === true, "ルール違反は error(rule)+resync");

// スタンプ(event)
a.say({ t: "event", k: "stamp", d: { id: 3 } });
await sleep(300);
ok(b.last("event")?.d?.id === 3, "スタンプが相手に届く");

// 最後まで: 全部出すと result が1回だけ
for (const w of [a, b]) for (const m of [...w.last("state").view.hand]) { w.say({ t: "act", a: { type: "play", n: m } }); await sleep(80); }
await sleep(300);
ok(a.all("result").length === 1 && b.all("result").length === 1, "対戦が終わると result が1回");

// 部屋コード(4文字・パスワードなし)
const c = await client(); const d = await client();
c.say({ t: "register", name: "う", mode: "friend" }); await sleep(300);
const code = c.last("waiting")?.room;
ok(/^[A-HJ-NP-Z2-9]{4}$/.test(code || ""), "部屋コードは4文字の英数");
d.say({ t: "register", name: "え", mode: "friend", room: (code || "").toLowerCase() }); await sleep(400);
ok(d.last("match")?.you === 1 && c.last("state"), "小文字のコードで入れて、対戦が始まる");

// 相手が切れたら勝ち
c.ws.close(); await sleep(500);
ok(d.last("result")?.why === "left", "相手が切れたら、残りの人の勝ち");

for (const w of [old, a, b, c, d]) try { w.ws.close(); } catch (_) {}
console.log(failed ? `失敗: ${failed}` : "すべて ok");
process.exit(failed ? 1 : 0);
