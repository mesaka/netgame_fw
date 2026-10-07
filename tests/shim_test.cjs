// webbridge.SHIM(JS)を、偽の WebSocket・localStorage で動かして確かめる(pytest から呼ばれる)。
const fs = require("fs");
class FakeWS { constructor(u) { this.url = u; this.sent = []; FakeWS.last = this; } send(s) { this.sent.push(s); } close() { this.onclose && this.onclose(); } }
global.window = global; global.WebSocket = FakeWS;
global.location = { protocol: "https:", host: "game.example", search: "" };
const store = {};
global.localStorage = { setItem: (k, v) => { store[k] = v; }, getItem: (k) => (k in store ? store[k] : null) };
global.navigator = {};
eval(fs.readFileSync(process.argv[2], "utf8"));
const N = window.ngNet;
const must = (c, m) => { if (!c) throw new Error(m); };

N.open("", "game=pokoten&v=1");
must(FakeWS.last.url === "wss://game.example/ws?game=pokoten&v=1", "url " + FakeWS.last.url);
must(N.state === "connecting", "state");
FakeWS.last.onopen(); must(N.state === "open" && N.opened, "open");
FakeWS.last.onmessage({ data: JSON.stringify({ t: "chat", text: "よろしく！😀" }) });
FakeWS.last.onmessage({ data: "pong" });
const got = N.take().split("\n");
must(got.length === 2 && /^[\x00-\x7f]*$/.test(got[0]), "ascii " + got);
must(JSON.parse(got[0]).text === "よろしく！😀", "roundtrip");
must(N.take() === "", "empty");
N.send("ping"); must(FakeWS.last.sent[0] === "ping", "send");
const old = FakeWS.last;
N.open("wss://x/ws?a=1", "game=g&v=1");                       // 接続先を指定し、すでにクエリがあれば & でつなぐ
must(FakeWS.last.url === "wss://x/ws?a=1&game=g&v=1", "url2 " + FakeWS.last.url);
old.onmessage({ data: "stale" }); must(N.take() === "", "stale");
FakeWS.last.onerror(); must(N.state === "closed", "closed");

location.search = "?server=wss%3A%2F%2Fother.example%2Fws";    // ページのURLで、接続先を変えられる
N.open("", "game=g&v=1");
must(FakeWS.last.url === "wss://other.example/ws?game=g&v=1", "override " + FakeWS.last.url);

N.store("k", '"\\u3042\\u3044"'); must(store.k === "あい", "store");
must(JSON.parse(N.load("k")) === "あい" && /^[\x00-\x7f]*$/.test(N.load("k")), "load");
must(N.load("none") === "null", "load none");
console.log("shim ok");
