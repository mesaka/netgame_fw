// テスト用の部品(偽のソケット・偽の host)。本番のコードからは使わない。
import { NetGameCore } from "./core.js";

export class FakeWS {
  constructor() { this.att = null; this.out = []; this.closed = false; }
  serializeAttachment(a) { this.att = JSON.parse(JSON.stringify(a)); }
  deserializeAttachment() { return this.att; }
  send(s) { this.out.push(JSON.parse(s)); }
  close() { this.closed = true; }
  last(t) { return [...this.out].reverse().find((m) => m.t === t); }
  all(t) { return this.out.filter((m) => m.t === t); }
}

/** games を載せた核と、ソケットを開く・送る・閉じる・時計を進める道具を返す。 */
export function setup(games, { random } = {}) {
  const socks = [];
  const store = new Map();
  let now = 1000;
  let alarm = null;      // host.setAlarm で予約された時刻(なければ null)
  // Workers の getWebSockets() は、毎回別のオブジェクトを返す。実際と同じに、Proxy で包んで返す
  const host = {
    sockets: () => socks.map((w) => new Proxy(w, {})),
    now: () => now,
    random: random || Math.random,
    setAlarm: (t) => { alarm = t; },
    deleteAlarm: () => { alarm = null; },
    kv: { get: (k) => store.get(k), put: (k, v) => store.set(k, v), delete: (k) => store.delete(k) },
  };
  const core = new NetGameCore(host, games);
  const open = (game, opts = {}) => {
    const w = new FakeWS();
    socks.push(w);
    core.onOpen(w, { game, ...opts });
    return w;
  };
  const say = (w, o) => core.onMessage(w, JSON.stringify(o));
  const close = (w) => { core.onClose(w); socks.splice(socks.indexOf(w), 1); };
  const tick = (ms) => { now += ms; };
  /** 予約された時刻まで時計を進めて、アラームを鳴らす(Durable Object の alarm() に当たる) */
  const fireAlarm = () => { if (alarm === null) return false; if (alarm > now) now = alarm; alarm = null; core.onAlarm(); return true; };
  const rooms = () => [...store.keys()].filter((k) => k.startsWith("room:"));
  return { core, open, say, close, tick, socks, store, rooms, fireAlarm, alarm: () => alarm };
}
