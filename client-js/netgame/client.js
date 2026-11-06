// netgame_fw の JS クライアント(通信と状態管理だけ。画面は含まない)。依存なし(ESM)。ブラウザと Node 22 以上で動く。
// 通信の仕様は docs/protocol.md、使いかたは docs/client-js.md。Python 版は client/netgame/session.py(同じ仕様の別実装)。
//
//   const net = new NetGameClient({ url: "wss://example.com/ws", game: "awase", v: 2, storage: localStorage });
//   net.on("state", ({ view, events, resync }) => { /* 盤面を更新(Promise を返せば、終わるまで次の通知を待つ) */ });
//   await net.connect();
//   net.registerRandom({ name: "ゲスト", settings: { rounds: 3 } });
//   net.act({ type: "play", card: 3 });
//
// 受信は、届いた順に1件ずつ処理する(ハンドラーが Promise を返したら、完了まで次の通知を待つ。アニメーションの途中で次の更新が来ても、順番が入れ替わらない)。
// 切れたら自動で再接続して、`resume`(部屋コード + token)で同じ席に戻る。再接続のあいだの送信(act など)は、古い盤面への操作になるので、捨てる(false を返す)。

const PING_MS = 20000;
const RECONNECT = { minMs: 1000, maxMs: 10000, factor: 1.3, giveUpMs: 300000 };

/** 制御文字を除き、前後の空白を削り、最大 max 文字(コードポイント)に切る(サーバーの cleanText と同じ) */
export function cleanText(s, max) {
  if (typeof s !== "string") return "";
  const t = s.replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, "").trim();
  return Array.from(t).slice(0, max).join("");
}

export class NetGameClient {
  /**
   * @param {object} o
   * @param {string} o.url        ws:// か wss:// の接続先(例: wss://example.com/ws)。?game=&v= は付けなくてよい
   * @param {string} o.game       ゲームID(サーバーのアダプターの id)
   * @param {number} [o.v=2]      プロトコルの版(authoritative は 2)
   * @param {Storage} [o.storage] token と部屋コードの保存先(localStorage など。省略するとメモリだけ。ページを開き直しての再接続には要る)
   * @param {object} [o.reconnect] { minMs, maxMs, factor, giveUpMs } 自動再接続。false で無効
   * @param {object} [o.timer] { set(fn, ms) → ハンドル, clear(ハンドル), now() } 再接続の待ち時間に使う時計(テスト用。省略時は setTimeout / Date.now)
   * @param {Function} [o.WebSocket] WebSocket のコンストラクター(省略時はグローバル)
   */
  constructor({ url, game, v = 2, storage = null, reconnect = {}, WebSocket: WS = globalThis.WebSocket, defaultName = "相手", timer = null } = {}) {
    if (!url || !game) throw new Error("url と game が要ります");
    if (!WS) throw new Error("WebSocket がありません(Node 22 未満なら、WebSocket オプションに ws などを渡す)");
    Object.assign(this, { url, game, v, storage, WS, defaultName });
    this.reconnectOpts = reconnect === false ? null : { ...RECONNECT, ...reconnect };
    this.timer = timer || { set: (fn, ms) => { const h = setTimeout(fn, ms); h.unref?.(); return h; }, clear: (h) => clearTimeout(h), now: () => Date.now() };
    this._handlers = new Map();
    this._queue = Promise.resolve();
    this._ws = null;
    this._timers = { ping: null, retry: null };
    this._buf = [];
    this._closing = false;
    this._tries = 0;
    this._lostAt = 0;
    this._connecting = null;
    this._opened = false;
    this._resuming = null;           // { room, token }: 新しい接続の hello を待って、resume を送る
    this.status = "closed";          // "connecting" | "open" | "reconnecting" | "closed"
    this._resetAll();
  }

  _resetAll() {
    this.phase = "closed";           // connecting → idle → waiting → ready → playing → over / resuming / closed
    this.error = null;               // "connect"(つながらない) / "lost"(途切れた) / "game" / "version"
    this.connId = null;
    this.config = {};
    this.token = "";                 // 再接続用の席の合言葉(v=2 authoritative)。画面には出さない
    this.room = "";                  // 部屋コード
    this.name = "";
    this._resetMatch();
    this.chat = [];
    this.errors = [];
    this.ruleErrors = [];
  }

  _resetMatch() {
    this.seat = null;
    this.players = [];
    this.seed = null;
    this.mode = null;                // "realtime" | "turns" | "authoritative"
    this.settings = {};
    this.readySeats = new Set();
    this.readySent = false;
    this.pausedSeats = new Set();
    this.offline = new Set();
    this.leftSeats = new Set();
    this.rematchSeats = new Set();
    this.turn = null;
    this.view = null;                // authoritative: いまの自分の view
    this.seq = null;
    this.events = [];                // 直近の state の events
    this.resync = false;
    this.relayed = [];               // 他の席から中継された event: [{seat, k, d}]
    this.result = null;              // { ranks, why }
    this.resultNo = 0;
  }

  // ---- イベント ----
  /** type: hello registered waiting match ready_state start state result presence resumed event chat paused action turn desync
   *        rematch_req player_left error resume_failed status。戻り値は、登録を外す関数。 */
  on(type, fn) {
    if (!this._handlers.has(type)) this._handlers.set(type, new Set());
    this._handlers.get(type).add(fn);
    return () => this._handlers.get(type)?.delete(fn);
  }
  off(type, fn) { this._handlers.get(type)?.delete(fn); }

  /** 受信の処理がすべて終わるまで待つ(テスト・画面の切り替えの前に) */
  idle() { return this._queue; }

  _emit(type, data) {
    const hs = [...(this._handlers.get(type) || [])];
    return Promise.all(hs.map(async (h) => {
      try { await h(data); } catch (e) { console.error("netgame handler error:", e); }
    }));
  }

  _setStatus(s) {
    if (this.status === s) return;
    this.status = s;
    this._emit("status", s);
  }

  // ---- 接続 ----
  _fullUrl() {
    return this.url + (this.url.includes("?") ? "&" : "?") + `game=${encodeURIComponent(this.game)}&v=${this.v}`;
  }

  /** 接続して、hello が届いたら解決する。すでに接続中・接続済みなら、同じ Promise。 */
  connect() {
    if (this._connecting) return this._connecting;
    this._closing = false;
    this._tries = 0;
    this._connecting = new Promise((resolve, reject) => { this._connectDone = { resolve, reject }; });
    this._connecting.catch(() => {});
    this.phase = "connecting";
    this._setStatus("connecting");
    this._open();
    return this._connecting;
  }

  _open() {
    let ws;
    try { ws = new this.WS(this._fullUrl()); } catch (_) { return this._onSocketClose(null, ws); }
    this._ws = ws;
    ws.addEventListener("open", () => {
      if (this._ws !== ws) return;
      this._opened = true;
      this._tries = 0;
      this._startPing();
      for (const s of this._buf.splice(0)) ws.send(s);
    });
    ws.addEventListener("message", (e) => {
      if (this._ws !== ws) return;
      let m;
      try { m = JSON.parse(typeof e.data === "string" ? e.data : String(e.data)); } catch (_) { return; }   // "pong" など
      if (!m || typeof m.t !== "string") return;
      this._queue = this._queue.then(() => this._handle(m)).catch((err) => console.error(err));
    });
    ws.addEventListener("error", () => {});
    // close も、メッセージと同じ順番で処理する(直前に届いた error などを処理してから、切断として扱う)
    ws.addEventListener("close", (e) => { this._queue = this._queue.then(() => this._onSocketClose(e && e.code, ws)).catch((err) => console.error(err)); });
  }

  _startPing() {
    clearInterval(this._timers.ping);
    this._timers.ping = setInterval(() => { if (this._ws && this._ws.readyState === 1) this._ws.send("ping"); }, PING_MS);
    this._timers.ping.unref?.();
  }

  _onSocketClose(code, ws) {
    if (ws && this._ws !== ws) return;           // 入れ替わった古い接続の close
    this._ws = null;
    clearInterval(this._timers.ping);
    if (this._closing) return this._finishClose(null);
    const canResume = this.reconnectOpts && this.token && this.room && !["closed", "connecting"].includes(this.phase);
    if (canResume) {
      if (!this._lostAt) this._lostAt = this.timer.now();
      if (this.timer.now() - this._lostAt > this.reconnectOpts.giveUpMs) return this._finishClose("lost");
      this._resuming = { room: this.room, token: this.token };
      this._setStatus("reconnecting");
      const o = this.reconnectOpts;
      const delay = Math.min(o.maxMs, o.minMs * o.factor ** this._tries) * (0.75 + Math.random() * 0.5);
      this._tries += 1;
      this._timers.retry = this.timer.set(() => { if (!this._closing) this._open(); }, delay);
      return undefined;
    }
    return this._finishClose(this._opened ? "lost" : "connect");
  }

  _finishClose(error) {
    this.timer.clear(this._timers.retry);
    if (error && !this.error) this.error = error;
    this.phase = "closed";
    this._setStatus("closed");
    if (this._connectDone) { this._connectDone.reject(new Error(this.error || "closed")); this._connectDone = null; }
    this._connecting = null;
    this._opened = false;
  }

  /** 接続を閉じる(自動再接続はしない)。サーバーからは「切断」に見える(猶予のあいだは席が残る)。部屋を出るなら leave()。 */
  close() {
    this._closing = true;
    this.timer.clear(this._timers.retry);
    clearInterval(this._timers.ping);
    const ws = this._ws;
    this._ws = null;
    try { ws && ws.close(); } catch (_) { /* すでに閉じている */ }
    this._finishClose(null);
  }

  // ---- 送信 ----
  _send(obj) {
    if (this.status === "reconnecting") return false;     // 再接続のあいだ(hello が届くまで)は、何も送らない。古い盤面への操作になる
    const text = JSON.stringify(obj);
    const ws = this._ws;
    if (ws && ws.readyState === 1) { ws.send(text); return true; }
    if (ws && ws.readyState === 0 && this.status === "connecting") { this._buf.push(text); return true; }   // 最初の接続の完了前だけ、ためておく
    return false;
  }

  /** ランダムマッチ。settings が同じ人どうしが組み合わさる。 */
  registerRandom({ name, settings } = {}) {
    return this._register({ name, mode: "random", settings });
  }

  /** ルーム対戦。room なし = 部屋を作って待つ。room あり = その部屋に入る。pass は、ゲームの設定(rooms.password)に従う。 */
  registerFriend({ name, settings, room, pass } = {}) {
    return this._register({ name, mode: "friend", settings, room, pass });
  }

  _register({ name, mode, settings, room, pass }) {
    const clean = cleanText(name, this.config.limits?.name ?? 8);
    if (this.phase !== "idle" || !clean) return false;
    const msg = { t: "register", name: clean, mode };
    if (settings && Object.keys(settings).length) msg.settings = settings;
    if (mode === "friend") {
      if (pass) msg.pass = String(pass);
      if (room) msg.room = String(room);
    }
    this.name = clean;
    this._send(msg);
    this.phase = "waiting";
    return true;
  }

  /** 準備OK(flow.ready が true のゲームだけ) */
  ready() {
    if (this.phase !== "ready" || this.readySent) return false;
    this.readySent = true;
    return this._send({ t: "ready" });
  }

  /** authoritative: 手を送る。結果は、サーバーから state で届く(自分の盤面は、それまで変えない) */
  act(action) {
    if (this.phase !== "playing") return false;
    return this._send({ t: "act", a: action === undefined ? {} : action });
  }

  /** 自分の最新の view を、もう一度送ってもらう */
  requestResync() { return this.phase === "playing" ? this._send({ t: "resync" }) : false; }

  /** 他の席へ中継するイベント(スタンプなど。アダプターの events に登録のある k だけ) */
  event(k, d = {}) { return this.phase === "playing" ? this._send({ t: "event", k, d }) : false; }

  /** turns: 手 / 状態のハッシュ / 終局の申告(v1 の方式。authoritative では使わない) */
  action(seq, d = {}) { return this.phase === "playing" ? this._send({ t: "action", seq, d }) : false; }
  sync(seq, h) { return this.phase === "playing" ? this._send({ t: "sync", seq, h: String(h).slice(0, 64) }) : false; }
  finish(ranks) { return this.phase === "playing" ? this._send({ t: "finish", ranks }) : false; }

  pause(on) { return this.phase === "playing" ? this._send({ t: "pause", on: !!on }) : false; }

  /** チャットを送る(履歴は this.chat) */
  say(text) {
    const t = cleanText(text, this.config.limits?.chat ?? 30);
    if (!t || !["ready", "playing", "over"].includes(this.phase)) return false;
    return this._send({ t: "chat", text: t });
  }

  rematch() {
    if (this.phase !== "over") return false;
    this.rematchSeats.add(this.seat);
    return this._send({ t: "rematch" });
  }

  /** 部屋を出る(すぐ退出。猶予なし)。保存した token も消す。 */
  leave() {
    this._send({ t: "leave" });
    this.forget();
    this._resetMatch();
    this.token = "";
    this.room = "";
    if (this.phase !== "closed") this.phase = "idle";
    return true;
  }

  /** 切れた席に戻る。hello のあと(phase が idle)に呼ぶ。{room, token} を省くと、いまの値か保存した値を使う。 */
  resume({ room, token } = {}) {
    const s = room && token ? { room, token } : (this.room && this.token ? { room: this.room, token: this.token } : this.savedSession());
    if (!s || this.phase !== "idle") return false;
    this.phase = "resuming";
    return this._send({ t: "resume", room: s.room, token: s.token });
  }

  // ---- 保存(token と部屋コード) ----
  _key() { return "netgame." + this.game; }
  savedSession() {
    try {
      const s = this.storage && JSON.parse(this.storage.getItem(this._key()) || "null");
      return s && s.room && s.token ? s : null;
    } catch (_) { return null; }
  }
  _persist() {
    if (!this.storage || !this.room || !this.token) return;
    try { this.storage.setItem(this._key(), JSON.stringify({ room: this.room, token: this.token })); } catch (_) { /* 保存できなくても動く */ }
  }
  forget() {
    try { this.storage && this.storage.removeItem(this._key()); } catch (_) { /* 同上 */ }
  }

  // ---- 受信の処理(届いた順に1件ずつ) ----
  async _handle(m) {
    const data = this._apply(m);
    if (data !== undefined) await this._emit(m.t, data);
  }

  /** 状態を更新して、通知する中身を返す(通知しないなら undefined) */
  _apply(m) {
    const lim = this.config.limits || {};
    switch (m.t) {
      case "hello": {
        if (m.v !== this.v) { this.error = "version"; this.close(); return undefined; }
        this.connId = String(m.id || "");
        this.config = m.config || {};
        this.error = null;
        this.phase = "idle";
        this._setStatus("open");
        if (this._connectDone) { this._connectDone.resolve(this.config); this._connectDone = null; }
        if (this._resuming) {                                      // 再接続: 新しい接続から、同じ席に戻る
          const r = this._resuming;
          this._resuming = null;
          this.phase = "resuming";
          this._send({ t: "resume", room: r.room, token: r.token });
        }
        return m;
      }
      case "registered":
        if (m.token) this.token = String(m.token);
        return m;
      case "waiting":
        if (m.room) { this.room = String(m.room); this._persist(); }
        if (this.phase === "idle") this.phase = "waiting";
        return m;
      case "match": {
        const players = (m.players || []).map((p, i) => ({ seat: Number(p.seat ?? i), name: cleanText(p.name ?? "", lim.name ?? 8) || this.defaultName }));
        const you = Number(m.you ?? 0);
        if (["ready", "playing"].includes(this.phase) && m.seed === this.seed && you === this.seat
            && JSON.stringify(players) === JSON.stringify(this.players)) return undefined;   // 同じ組み合わせの match がもう一度届いても、状態は変えない
        this._resetMatch();
        this.seat = you; this.players = players; this.seed = m.seed ?? null;
        this.settings = m.settings || {};
        this.mode = m.mode || "realtime";
        if (m.room) { this.room = String(m.room); this._persist(); }
        this.phase = "ready";
        return m;
      }
      case "ready_state":
        if (this.phase === "ready") this.readySeats = new Set((m.seats || []).map(Number));
        return m;
      case "start":
        if (this.phase !== "ready") return undefined;
        this.phase = "playing";
        this.turn = m.turn ? { seat: Number(m.turn.seat), seq: Number(m.turn.seq) } : null;
        return m;
      case "state":
        if (this.phase !== "playing") return undefined;
        this.view = m.view; this.seq = m.seq; this.events = m.events || []; this.resync = !!m.resync;
        return { seq: m.seq, view: m.view, events: this.events, resync: this.resync };
      case "result": {
        if (this.phase === "over" && !this.result) { /* 再接続で、終わった部屋に戻った */ } else if (!["ready", "playing"].includes(this.phase)) return undefined;
        this.result = { ranks: m.ranks || [], why: m.why || "normal" };
        this.resultNo += 1;
        const stay = this.mode === "authoritative" && this.config.flow?.rematch === "game" && this.result.why === "normal";
        if (!stay) this.phase = "over";            // flow.rematch が "game" の部屋は playing のまま(結果は通知だけ)
        if (this.result.why === "left") for (const p of this.players) if (p.seat !== this.seat) this.leftSeats.add(p.seat);
        return m;
      }
      case "presence":
        if (m.online) this.offline.delete(Number(m.seat)); else this.offline.add(Number(m.seat));
        return m;
      case "resumed": {
        this._resetMatch();
        this.seat = Number(m.you); this.room = String(m.room); this.seed = m.seed ?? null;
        this.players = (m.players || []).map((p) => ({ seat: Number(p.seat), name: cleanText(p.name ?? "", lim.name ?? 8) || this.defaultName }));
        this.settings = m.settings || {}; this.mode = m.mode || "realtime";
        this.phase = ["waiting", "ready", "playing", "over"].includes(m.status) ? m.status : "playing";
        this._lostAt = 0;
        this._persist();
        return m;
      }
      case "event":
        if (this.phase === "playing") this.relayed.push({ seat: Number(m.seat), k: String(m.k), d: m.d ?? {} });
        return this.phase === "playing" ? m : undefined;
      case "chat": {
        const text = cleanText(m.text ?? "", lim.chat ?? 30);
        if (!text) return undefined;
        this.chat.push({ mine: m.seat === this.seat, name: cleanText(m.name ?? "", lim.name ?? 8), text });
        this.chat = this.chat.slice(-30);
        return m;
      }
      case "paused":
        if (this.phase !== "playing") return undefined;
        if (m.on === true) this.pausedSeats.add(Number(m.seat)); else this.pausedSeats.delete(Number(m.seat));
        return m;
      case "action": case "turn":
        if (this.phase !== "playing") return undefined;
        if (m.t === "turn") this.turn = { seat: Number(m.seat), seq: Number(m.seq) };
        return m;
      case "desync": return m;
      case "rematch_req": this.rematchSeats.add(Number(m.seat)); return m;
      case "player_left": this.leftSeats.add(Number(m.seat)); return m;
      case "error": {
        const code = String(m.code || "server");
        this.errors.push(code);
        if (code === "rule") this.ruleErrors.push(m.d);
        if (code === "resume") {                                    // 戻れない(部屋がない・合言葉が違う・猶予切れ)
          this.forget();
          this.token = ""; this.room = ""; this._resuming = null; this._lostAt = 0;
          if (this.phase === "resuming") { this.phase = "idle"; this._resetMatch(); }
          this._emit("resume_failed", { code });
        } else if (["name", "key", "room", "pass"].includes(code)) {
          if (this.phase === "waiting") this.phase = "idle";        // 登録は受け付けられなかった。やり直せる
        } else if (code === "game" || code === "version") {
          this.error = code;
          this._closing = true;
        }
        return m;
      }
      default: return undefined;
    }
  }

  /** 状態の一覧(適合テストと、デバッグ用)。Python 版の NetSession.snapshot() と同じ形。 */
  snapshot() {
    return {
      phase: this.phase,
      seat: this.players.length ? this.seat : null,
      players: this.players.map((p) => ({ seat: p.seat, name: p.name })),
      room: this.room ? "<room>" : null,
      hasToken: !!this.token,
      seq: this.seq,
      view: this.view,
      events: this.events,
      resync: this.resync,
      relayed: this.relayed.map((e) => [e.seat, e.k, e.d]),
      result: this.result,
      offline: [...this.offline].sort((a, b) => a - b),
      chat: this.chat.map((c) => ({ mine: c.mine, name: c.name, text: c.text })),
      errors: [...this.errors],
      ruleErrors: [...this.ruleErrors],
    };
  }
}
