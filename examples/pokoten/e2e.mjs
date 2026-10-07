// 本物の Workers ランタイム(wrangler dev)に、WebSocket でつないで、通しで確かめる。
//   npx wrangler dev -c examples/pokoten/wrangler.jsonc --port 8787 &
//   node examples/pokoten/e2e.mjs [ws://localhost:8787/ws]
const URL_ = process.argv[2] || "ws://localhost:8787/ws";

function client(name) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(`${URL_}?game=pokoten&v=1`);
    const c = { name, inbox: [], ws };
    ws.onmessage = (e) => { if (e.data !== "pong") c.inbox.push(JSON.parse(e.data)); };
    ws.onopen = () => resolve(c);
    ws.onerror = (e) => reject(new Error("接続できません: " + URL_));
    c.send = (o) => ws.send(JSON.stringify(o));
    c.wait = async (t, ms = 4000) => {
      const end = Date.now() + ms;
      for (;;) {
        const i = c.inbox.findIndex((m) => m.t === t);
        if (i >= 0) return c.inbox.splice(i, 1)[0];
        if (Date.now() > end) throw new Error(`${name}: ${t} が届きません(届いたもの: ${c.inbox.map((m) => m.t)})`);
        await new Promise((r) => setTimeout(r, 20));
      }
    };
  });
}
const ok = (c, msg) => { if (!c) throw new Error("失敗: " + msg); console.log("ok:", msg); };

const a = await client("A"); const b = await client("B");
const ha = await a.wait("hello"); await b.wait("hello");
ok(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/.test(ha.id) && ha.v === 1, "hello(接続ID・版)");

// ランダム
a.send({ t: "register", name: "たろう", mode: "random", settings: { diff: "hard" } });
await a.wait("registered"); await a.wait("waiting");
b.send({ t: "register", name: "はなこ", mode: "random", settings: { diff: "hard" } });
const ma = await a.wait("match"); const mb = await b.wait("match");
ok(ma.seed === mb.seed && ma.you === 0 && mb.you === 1, "ランダムで組まれる(同じ seed・席)");
a.send({ t: "ready" }); await b.wait("ready_state");
b.send({ t: "ready" }); await a.wait("start"); await b.wait("start");
ok(true, "準備OK → start");
a.send({ t: "event", k: "attack", d: { n: 1 } });
ok((await b.wait("event")).k === "attack", "attack が相手へ届く");
a.send({ t: "pause", on: true });
ok((await b.wait("paused")).on === true, "一時停止が届く");
b.send({ t: "chat", text: "よろしく！" });
ok((await a.wait("chat")).text === "よろしく！", "日本語のチャットが届く");
a.send({ t: "event", k: "over", d: {} });
const r = await b.wait("result");
ok(r.ranks.find((x) => x.seat === 1).rank === 1, "負けの申告で、相手が勝ち");
a.send({ t: "rematch" }); b.send({ t: "rematch" });
await a.wait("match"); await b.wait("match");
ok(true, "再戦で新しい match");

// ルーム
const h = await client("H"); const g = await client("G");
await h.wait("hello"); await g.wait("hello");
h.send({ t: "register", name: "ホスト", mode: "friend", pass: "4321", settings: { diff: "easy" } });
const w = await h.wait("waiting");
ok(/^\d{6}$/.test(w.room), "ルームIDが発行される");
g.send({ t: "register", name: "ゲスト", mode: "friend", room: w.room, pass: "0000" });
ok((await g.wait("error")).code === "pass", "パスワード違いで入れない");
g.send({ t: "register", name: "ゲスト", mode: "friend", room: w.room, pass: "4321" });
const mg = await g.wait("match");
ok(mg.settings.diff === "easy" && mg.players.length === 2, "ルームに入れる(設定は作った人のもの)");

// 退出
h.ws.close();
const lr = await g.wait("result");
ok(lr.why === "left" && lr.ranks.find((x) => x.seat === 1).rank === 1, "相手が切れたら勝ち");
for (const c of [a, b, g]) c.ws.close();
console.log("すべて ok");
process.exit(0);
