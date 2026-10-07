// netgame_fw サーバーの核。Cloudflare に依存しない(node --test でテストできる)。
// 通信の仕様は docs/protocol.md、ゲーム側の書き方(アダプター)は docs/adapter.md。
//
// 流れ: 接続(hello)→ register(名前・ランダム/ルーム)→ 部屋が決まる(match)→ 全員 ready → start → 対戦 → result → rematch / 退出。
// realtime: ゲームが登録したイベント(event)を中継する。turns: 手番・通し番号・ハッシュの突き合わせをサーバーが行う。
//
// 状態の置き場所:
//   ソケットごとの付属情報(attachment): { id, game, state: "new"|"queued"|"room", name, roomId, seat, matchKey, since, lastChat }
//   部屋(room)の記録: host.kv に "room:<ルームID>" で JSON として保存(Durable Object の休止をまたいでも失われない)
import { clampInt, cleanText } from "./text.js";

export const PROTOCOL_VERSION = 1;
export const DEFAULT_LIMITS = {
  name: 8,             // プレイヤーネーム(文字数)
  chat: 30,            // チャット(文字数・全角30文字)
  chatIntervalMs: 400, // チャットの連投を止める間隔
  actionBytes: 4096,   // event / action の中身の大きさ
  frameBytes: 8192,    // 受け取る1フレームの大きさ
  passFails: 5,        // パスワードを間違えられる回数(超えるとその部屋は閉じる)
};
const PASS_RE = /^[0-9]{4}$/;
const ROOM_RE = /^[0-9]{6}$/;
const ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // 紛らわしい文字(I O 0 1)を除く

export class NetGameCore {
  /**
   * host: { sockets(): WebSocket[], now(): number, random(): number, kv: { get(k), put(k, v), delete(k) } }
   *       sockets の要素は send / close / serializeAttachment / deserializeAttachment を持つ。
   * games: { [gameId]: adapter }
   */
  constructor(host, games) {
    this.host = host;
    this.games = games;
    this.rate = new Map(); // event の回数制限(メモリだけ。休止で消えてよい)
  }

  // ---- 小さな部品 ----
  _now() { return this.host.now ? this.host.now() : Date.now(); }
  _rand() { return this.host.random ? this.host.random() : Math.random(); }
  _att(ws) { return ws.deserializeAttachment() || {}; }
  _set(ws, patch) {
    const a = { ...this._att(ws), ...patch };
    ws.serializeAttachment(a);
    return a;
  }
  _send(ws, obj) {
    try { ws.send(JSON.stringify(obj)); } catch (_) { /* 切れている相手には送れない */ }
  }
  _error(ws, code, d) { this._send(ws, d === undefined ? { t: "error", code } : { t: "error", code, d }); }
  _sockById(id) { return this.host.sockets().find((w) => this._att(w).id === id) || null; }
  _adapter(att) { return this.games[att.game]; }
  _limits(adapter) { return { ...DEFAULT_LIMITS, ...(adapter.limits || {}) }; }
  _max(adapter) { return adapter.maxPlayers || 2; }
  _min(adapter) { return adapter.minPlayers || 2; }

  _getRoom(id) {
    const v = this.host.kv.get("room:" + id);
    return v ? JSON.parse(v) : null;
  }
  _putRoom(rec) { this.host.kv.put("room:" + rec.id, JSON.stringify(rec)); }
  _delRoom(rec) { this.host.kv.delete("room:" + rec.id); rec.deleted = true; }
  _save(rec) { if (!rec.deleted) this._putRoom(rec); }

  _newConnId() {
    const used = new Set(this.host.sockets().map((w) => this._att(w).id));
    for (;;) {
      let s = "";
      for (let i = 0; i < 8; i++) s += ID_CHARS[Math.floor(this._rand() * ID_CHARS.length)];
      const id = s.slice(0, 4) + "-" + s.slice(4);
      if (!used.has(id)) return id;
    }
  }
  _newRoomId() {
    for (;;) {
      const id = String(100000 + Math.floor(this._rand() * 900000));
      if (!this.host.kv.get("room:" + id)) return id;
    }
  }

  /** 部屋にいる(退出していない)人の席の一覧 */
  _present(rec) { return rec.players.map((p, i) => (p.left ? -1 : i)).filter((i) => i >= 0); }
  _broadcast(rec, obj, exceptSeat = -1) {
    for (const seat of this._present(rec)) {
      if (seat === exceptSeat) continue;
      const w = this._sockById(rec.players[seat].id);
      if (w) this._send(w, obj);
    }
  }

  /** アダプターのコールバックに渡す、部屋の窓口 */
  _roomApi(rec) {
    return {
      id: rec.id,
      players: rec.players.map((p, i) => ({ seat: i, name: p.name, left: !!p.left })),
      settings: rec.settings,
      finish: (ranks, why = "normal") => this._finish(rec, ranks, why),
    };
  }

  // ---- 接続 ----
  onOpen(ws, { game, v } = {}) {
    const adapter = this.games[game];
    if (!adapter) { this._error(ws, "game"); try { ws.close(1008, "game"); } catch (_) {} return; }
    if (v !== undefined && Number(v) !== PROTOCOL_VERSION) {
      this._error(ws, "version"); try { ws.close(1008, "version"); } catch (_) {} return;
    }
    const id = this._newConnId();
    ws.serializeAttachment({ id, game, state: "new" });
    this._send(ws, {
      t: "hello", id, v: PROTOCOL_VERSION, game,
      config: { min_players: this._min(adapter), max_players: this._max(adapter), mode: adapter.mode || "realtime",
                limits: this._limits(adapter) },
    });
  }

  onClose(ws) {
    this._leave(this._att(ws), false);
  }

  // ---- メッセージ ----
  onMessage(ws, raw) {
    const me = this._att(ws);
    const adapter = this._adapter(me);
    if (!adapter || typeof raw !== "string" || raw.length > this._limits(adapter).frameBytes) return;
    let m;
    try { m = JSON.parse(raw); } catch (_) { return; }
    if (!m || typeof m.t !== "string") return;
    switch (m.t) {
      case "register": return this._register(ws, me, adapter, m);
      case "ready": return this._ready(ws, me, adapter);
      case "pause": return this._pause(ws, me, m);
      case "event": return this._event(ws, me, adapter, m);
      case "action": return this._action(ws, me, adapter, m);
      case "sync": return this._sync(ws, me, adapter, m);
      case "finish": return this._clientFinish(ws, me, adapter, m);
      case "chat": return this._chat(ws, me, adapter, m);
      case "rematch": return this._rematch(ws, me, adapter);
      case "leave": return this._leaveMsg(ws, me);
      default: return undefined;
    }
  }

  // ---- 登録・組み合わせ ----
  _register(ws, me, adapter, m) {
    if (me.state !== "new") return;
    const lim = this._limits(adapter);
    const name = cleanText(m.name, lim.name);
    if (!name) return this._error(ws, "name");
    const settings = adapter.normalizeSettings ? adapter.normalizeSettings(m.settings) : (m.settings || {});
    if (m.mode === "friend") return this._registerFriend(ws, me, adapter, m, name, settings, lim);
    return this._registerRandom(ws, me, adapter, name, settings);
  }

  _registerRandom(ws, me, adapter, name, settings) {
    const key = String(adapter.matchKey ? adapter.matchKey(settings) : "");
    this._set(ws, { name, settings, matchKey: key, state: "queued", since: this._now() });
    this._send(ws, { t: "registered", id: me.id, name });
    const need = this._max(adapter) - 1;
    const others = this.host.sockets()
      .map((w) => [w, this._att(w)])
      .filter(([, a]) => a.id !== me.id && a.state === "queued" && a.game === me.game && a.matchKey === key)
      .sort((x, y) => x[1].since - y[1].since)
      .slice(0, need);
    if (others.length < need) return this._send(ws, { t: "waiting" });
    // 先に待っていた人から順に 0,1,… の席
    const group = [...others.map(([w, a]) => ({ ws: w, name: a.name, settings: a.settings })),
                   { ws, name, settings }];
    const rec = {
      id: this._newRoomId(), game: me.game, kind: "random", mode: adapter.mode || "realtime",
      players: group.map((g) => ({ id: this._att(g.ws).id, name: g.name })),
      settings: group[0].settings, state: "waiting",
    };
    group.forEach((g, seat) => this._set(g.ws, { state: "room", roomId: rec.id, seat }));
    this._beginMatch(rec, adapter);
  }

  _registerFriend(ws, me, adapter, m, name, settings, lim) {
    if (typeof m.pass !== "string" || !PASS_RE.test(m.pass)) return this._error(ws, "key");
    if (typeof m.room === "string" && m.room !== "") {                 // 既存のルームに入る
      const rec = ROOM_RE.test(m.room) ? this._getRoom(m.room) : null;
      if (!rec || rec.game !== me.game || rec.kind !== "friend" || rec.state !== "waiting"
          || rec.players.length >= this._max(adapter) || (rec.fails || 0) >= lim.passFails) {
        return this._error(ws, "room");                                  // 登録はしない(やり直せる)
      }
      if (rec.pass !== m.pass) {
        rec.fails = (rec.fails || 0) + 1;                                // 総当たり対策: 間違いが続いたら部屋は閉じる
        this._putRoom(rec);
        return this._error(ws, "pass");
      }
      const seat = rec.players.length;
      rec.players.push({ id: me.id, name });
      this._set(ws, { name, state: "room", roomId: rec.id, seat });
      this._send(ws, { t: "registered", id: me.id, name });
      if (rec.players.length >= this._max(adapter)) return this._beginMatch(rec, adapter);
      this._putRoom(rec);
      return this._send(ws, { t: "waiting", room: rec.id });
    }
    const rec = {                                                       // ルームを作って待つ
      id: this._newRoomId(), game: me.game, kind: "friend", mode: adapter.mode || "realtime",
      pass: m.pass, fails: 0, players: [{ id: me.id, name }], settings, state: "waiting",
    };
    this._set(ws, { name, state: "room", roomId: rec.id, seat: 0 });
    this._putRoom(rec);
    this._send(ws, { t: "registered", id: me.id, name });
    this._send(ws, { t: "waiting", room: rec.id });
  }

  /** 人数がそろった。準備中(ready)にして、全員へ match を送る。再戦でも使う。 */
  _beginMatch(rec, adapter) {
    rec.state = "ready";
    rec.seed = Math.floor(this._rand() * (1 << 30));
    rec.ready = [];
    rec.rematch = [];
    rec.turn = null;
    rec.hashes = {};
    rec.finishes = {};
    rec.result = null;
    this._save(rec);
    const players = rec.players.map((p, seat) => ({ seat, name: p.name }));
    for (const seat of this._present(rec)) {
      const w = this._sockById(rec.players[seat].id);
      if (w) this._send(w, { t: "match", seed: rec.seed, you: seat, players, settings: rec.settings, mode: rec.mode });
    }
  }

  // ---- 準備・一時停止 ----
  /** me が入っている部屋と席(部屋にいなければ null) */
  _ctx(me) {
    if (me.state !== "room" || !me.roomId) return null;
    const rec = this._getRoom(me.roomId);
    return rec ? { rec, seat: me.seat } : null;
  }

  _ready(ws, me, adapter) {
    const c = this._ctx(me);
    if (!c || c.rec.state !== "ready" || c.rec.ready.includes(c.seat)) return;
    const { rec, seat } = c;
    rec.ready.push(seat);
    this._broadcast(rec, { t: "ready_state", seats: [...rec.ready].sort((a, b) => a - b) });
    if (rec.ready.length >= this._present(rec).length) {
      rec.state = "playing";
      rec.hashes = {};
      rec.finishes = {};
      if (rec.mode === "turns") {
        const first = adapter.turns && adapter.turns.firstTurn ? adapter.turns.firstTurn(this._roomApi(rec)) : 0;
        rec.turn = { seat: first, seq: 0 };
      }
      this._broadcast(rec, rec.turn ? { t: "start", turn: rec.turn } : { t: "start" });
    }
    this._save(rec);
  }

  /** チャットの入力中は、お互いのゲームを止める(状態は持たず、中継するだけ) */
  _pause(ws, me, m) {
    const c = this._ctx(me);
    if (!c || c.rec.state !== "playing") return;
    this._broadcast(c.rec, { t: "paused", seat: c.seat, on: m.on === true }, c.seat);
  }

  // ---- realtime: イベントの中継 ----
  _event(ws, me, adapter, m) {
    const c = this._ctx(me);
    if (!c || c.rec.mode !== "realtime" || c.rec.state !== "playing") return;
    const def = adapter.events && typeof m.k === "string" ? adapter.events[m.k] : null;
    if (!def) return this._error(ws, "state");
    const d = m.d === undefined ? {} : m.d;
    if (JSON.stringify(d).length > this._limits(adapter).actionBytes) return this._error(ws, "rate");
    if (def.validate && !def.validate(d)) return;
    if (def.maxPerSec) {
      const key = me.id + ":" + m.k;
      const now = this._now();
      const recent = (this.rate.get(key) || []).filter((t) => now - t < 1000);
      if (recent.length >= def.maxPerSec) return this._error(ws, "rate");
      recent.push(now);
      this.rate.set(key, recent);
    }
    if (def.to === "others") this._broadcast(c.rec, { t: "event", seat: c.seat, k: m.k, d }, c.seat);
    if (def.on) def.on(this._roomApi(c.rec), c.seat, d);
    this._save(c.rec);
  }

  // ---- turns: 手・手番・ハッシュの突き合わせ ----
  _action(ws, me, adapter, m) {
    const c = this._ctx(me);
    if (!c || c.rec.mode !== "turns" || c.rec.state !== "playing" || !c.rec.turn) return;
    const { rec, seat } = c;
    if (rec.turn.seat !== seat || m.seq !== rec.turn.seq) return this._error(ws, "state");
    const d = m.d === undefined ? {} : m.d;
    const limit = (adapter.turns && adapter.turns.maxActionBytes) || this._limits(adapter).actionBytes;
    if (JSON.stringify(d).length > limit) return this._error(ws, "rate");
    const api = this._roomApi(rec);
    if (adapter.turns && adapter.turns.validate && !adapter.turns.validate(api, seat, d)) return this._error(ws, "rule");
    this._broadcast(rec, { t: "action", seat, seq: rec.turn.seq, d });     // 本人にも返す(全員がサーバーの順で適用する)
    let next;
    if (adapter.turns && adapter.turns.nextTurn) next = adapter.turns.nextTurn(api, seat, d);
    else {
      const present = this._present(rec);
      next = present[(present.indexOf(seat) + 1) % present.length];
    }
    rec.turn = { seat: next, seq: rec.turn.seq + 1 };
    this._broadcast(rec, { t: "turn", seat: rec.turn.seat, seq: rec.turn.seq });
    this._save(rec);
  }

  _sync(ws, me, adapter, m) {
    const c = this._ctx(me);
    if (!c || c.rec.mode !== "turns" || c.rec.state !== "playing" || !c.rec.turn) return;
    const { rec, seat } = c;
    if (!Number.isInteger(m.seq) || m.seq < 0 || m.seq >= rec.turn.seq) return;   // まだ指されていない手のハッシュは受けない
    if (typeof m.h !== "string" || m.h.length === 0 || m.h.length > 64) return;
    const slot = (rec.hashes[m.seq] = rec.hashes[m.seq] || {});
    slot[seat] = m.h;
    const present = this._present(rec);
    if (!present.every((s) => slot[s] !== undefined)) return this._save(rec);
    const agreed = present.every((s) => slot[s] === slot[present[0]]);
    delete rec.hashes[m.seq];
    if (agreed) return this._save(rec);
    this._broadcast(rec, { t: "desync", seq: m.seq });                            // ずれた。対戦を止める
    this._finish(rec, present.map((s) => ({ seat: s, rank: 1 })), "desync");
  }

  // ---- 結果 ----
  _validRanks(rec, ranks) {
    if (!Array.isArray(ranks) || ranks.length !== rec.players.length) return false;
    const seats = new Set();
    for (const r of ranks) {
      if (!r || !Number.isInteger(r.seat) || r.seat < 0 || r.seat >= rec.players.length || seats.has(r.seat)) return false;
      if (!Number.isInteger(r.rank) || r.rank < 1) return false;
      seats.add(r.seat);
    }
    return true;
  }

  _normRanks(ranks) {
    return JSON.stringify([...ranks].sort((a, b) => a.seat - b.seat).map((r) => [r.seat, r.rank]));
  }

  /** 結果を確定する。状態は over になり、全員へ result を送る。 */
  _finish(rec, ranks, why) {
    if (rec.state === "over") return;
    rec.state = "over";
    rec.result = { ranks, why };
    rec.ready = [];
    rec.rematch = [];
    rec.finishes = {};
    rec.hashes = {};
    rec.turn = null;
    this._broadcast(rec, { t: "result", ranks, why });
    this._save(rec);
  }

  /** クライアントの finish。realtime はアダプターの onFinish が検証・確定する。turns は全員の申告が一致したら確定する。 */
  _clientFinish(ws, me, adapter, m) {
    const c = this._ctx(me);
    if (!c || c.rec.state !== "playing") return;
    const { rec, seat } = c;
    if (!this._validRanks(rec, m.ranks)) return this._error(ws, "state");
    if (rec.mode === "turns") {
      rec.finishes[seat] = m.ranks;
      const present = this._present(rec);
      if (!present.every((s) => rec.finishes[s])) return this._save(rec);
      const same = present.every((s) => this._normRanks(rec.finishes[s]) === this._normRanks(rec.finishes[present[0]]));
      if (same) return this._finish(rec, rec.finishes[present[0]], "normal");
      this._broadcast(rec, { t: "desync", seq: rec.turn ? rec.turn.seq : 0 });
      return this._finish(rec, present.map((s) => ({ seat: s, rank: 1 })), "desync");
    }
    if (!adapter.onFinish) return this._error(ws, "state");
    const ranks = adapter.onFinish(this._roomApi(rec), seat, m.ranks);
    if (ranks && this._validRanks(rec, ranks)) this._finish(rec, ranks, "normal");
    else this._save(rec);
  }

  // ---- チャット・再戦 ----
  _chat(ws, me, adapter, m) {
    const c = this._ctx(me);
    if (!c || c.rec.state === "waiting") return;
    const lim = this._limits(adapter);
    const text = cleanText(m.text, lim.chat);
    const now = this._now();
    if (!text || now - (me.lastChat || 0) < lim.chatIntervalMs) return;
    this._set(ws, { lastChat: now });
    this._broadcast(c.rec, { t: "chat", seat: c.seat, name: c.rec.players[c.seat].name, text });
  }

  _rematch(ws, me, adapter) {
    const c = this._ctx(me);
    if (!c || c.rec.state !== "over") return;
    const { rec, seat } = c;
    if (this._present(rec).length < rec.players.length) return;      // 誰かが退出していたら、再戦はできない
    if (rec.rematch.includes(seat)) return;
    rec.rematch.push(seat);
    if (rec.rematch.length >= rec.players.length) return this._beginMatch(rec, adapter);
    this._broadcast(rec, { t: "rematch_req", seat }, seat);
    this._save(rec);
  }

  // ---- 退出 ----
  _leaveMsg(ws, me) {
    this._leave(me, true);
    this._set(ws, { state: "new", roomId: null, seat: null });
  }

  _leave(me, keepSocket) {
    if (me.state !== "room" || !me.roomId) return;
    const rec = this._getRoom(me.roomId);
    if (!rec) return;
    const adapter = this.games[rec.game];
    const seat = me.seat;
    if (!rec.players[seat] || rec.players[seat].id !== me.id || rec.players[seat].left) return;
    rec.players[seat].left = true;
    const present = this._present(rec);
    if (present.length === 0 || rec.state === "waiting") {
      // 待機中に作った人が抜けたら、部屋は消える(3人以上の開始前の途中退出は、将来の拡張)
      if (rec.state === "waiting" && present.length > 0) { for (const s of present) this._detach(rec, s); }
      return this._delRoom(rec);
    }
    if (rec.state === "over") {
      this._broadcast(rec, { t: "player_left", seat });
      return this._save(rec);
    }
    const policy = adapter.onLeave || (this._max(adapter) === 2 ? "forfeit" : "abort");
    if (policy === "forfeit") {
      const ranks = rec.players.map((p, i) => ({ seat: i, rank: i === seat ? 2 : 1 }));
      return this._finish(rec, ranks, "left");
    }
    return this._finish(rec, present.map((s) => ({ seat: s, rank: 1 })), "abort");   // 3人以上の途中退出の扱い(続行など)は、将来の拡張
  }

  _detach(rec, seat) {
    const w = this._sockById(rec.players[seat].id);
    if (w) this._set(w, { state: "new", roomId: null, seat: null });
  }
}
