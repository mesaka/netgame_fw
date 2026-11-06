// 適合テストの「世界」: サーバーの核(NetGameCore)を、決定的な乱数・偽の時計で動かし、接続を ID で出し入れする。
// JS クライアントは、同じプロセスの中で(CoreSocket 経由)、Python クライアントは、host.mjs の標準入出力で、この世界につながる。
import { setup, FakeWS } from "../../server/testkit.js";
import cards from "../../examples/cards/adapter.js";

export const GAMES = { cards };
const lcg = (seed) => () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32);

/** sinks: 接続ID → ({m: 文字列} | {closed: コード}) を受ける関数(サーバー → クライアント) */
export function makeWorld({ games = GAMES, seed = 20260101 } = {}) {
  const env = setup(games, { random: lcg(seed) });
  const conns = new Map();
  const sinks = new Map();
  const out = (id, o) => { const f = sinks.get(id); if (f) f(o); };
  return {
    env,
    attach: (id, sink) => sinks.set(id, sink),
    open(id, game, v) {
      const w = new FakeWS();
      w.send = (s) => out(id, { m: s });
      w.close = (code) => { w.closed = true; out(id, { closed: code ?? 1000 }); };
      conns.set(id, w);
      env.socks.push(w);
      env.core.onOpen(w, { game, v: String(v) });
    },
    say(id, text) { const w = conns.get(id); if (w) env.core.onMessage(w, text); },
    /** クライアントから接続を閉じた */
    close(id) {
      const w = conns.get(id);
      if (!w) return;
      conns.delete(id);
      env.core.onClose(w);
      const i = env.socks.indexOf(w);
      if (i >= 0) env.socks.splice(i, 1);
    },
    tick: (ms) => env.tick(ms),
    alarm: () => env.fireAlarm(),
  };
}

/** WebSocket のふりをして、世界につなぐクラス(NetGameClient の WebSocket オプションに渡す) */
export function coreSocketClass(world) {
  let n = 0;
  return class CoreSocket {
    constructor(url) {
      const u = new URL(url.replace(/^ws/, "http"));
      this.id = "j" + ++n;
      this.readyState = 0;
      this._l = {};
      world.attach(this.id, (o) => {
        if (o.m !== undefined) this._emit("message", { data: o.m });
        else if (this.readyState < 3) { this.readyState = 3; this._emit("close", { code: o.closed }); }
      });
      queueMicrotask(() => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this._emit("open", {});
        world.open(this.id, u.searchParams.get("game"), u.searchParams.get("v"));
      });
    }
    addEventListener(t, f) { (this._l[t] ||= []).push(f); }
    _emit(t, e) { for (const f of this._l[t] || []) f(e); }
    send(text) { if (this.readyState !== 1) throw new Error("not open"); world.say(this.id, text); }
    close() {
      if (this.readyState >= 2) return;
      this.readyState = 3;
      world.close(this.id);
      queueMicrotask(() => this._emit("close", { code: 1000 }));
    }
    /** テスト用: サーバー側が気づかないまま、通信だけ途切れた(猶予のあいだ、席は残る) */
    _drop() {
      if (this.readyState >= 2) return;
      this.readyState = 3;
      world.close(this.id);
      this._emit("close", { code: 1006 });
    }
  };
}
