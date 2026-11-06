// Cloudflare Worker + Durable Object(WebSocket Hibernation)で、NetGameCore を動かす入口。
// ゲーム側は、自分のアダプターを渡して createGameWorker を呼び、Durable Object のクラスと fetch ハンドラーを受け取る:
//
//   import { createGameWorker } from "./netgame/server/worker.js";
//   import pokoten from "./pokoten_adapter.js";
//   const { Hub, handler } = createGameWorker({ pokoten });
//   export { Hub };            // wrangler.jsonc の durable_objects.bindings の class_name と同じ名前にする
//   export default handler;
//
// 接続先は `/ws?game=<ゲームID>&v=1`。/ws 以外は、このハンドラーでは扱わない(静的ファイルは run_worker_first で別に配る)。
// いまは、組み合わせも部屋も、1つの Durable Object(Hub)で動かす。部屋の記録は、その DO のストレージ(kv)に置く。
// (部屋ごとの Durable Object に分けるのは、規模が必要になってから。docs/design.md 3.3)
import { DurableObject } from "cloudflare:workers";
import { NetGameCore, hashClientKey, purgeLegacyJoinKeys } from "./core.js";

export function createGameWorker(games, { binding = "HUB", instance = "main" } = {}) {
  class Hub extends DurableObject {
    constructor(ctx, env) {
      super(ctx, env);
      // 古い版が生の IP をキーに残した、入室失敗の記録を、一度だけ消す(更新した最初の起動で)
      try { purgeLegacyJoinKeys(this.ctx.storage.kv); } catch (e) { console.error("purgeLegacyJoinKeys:", e); }
      this.core = new NetGameCore({
        sockets: () => this.ctx.getWebSockets(),
        now: () => Date.now(),
        random: () => Math.random(),
        kv: this.ctx.storage.kv,
        setAlarm: (t) => { this.ctx.storage.setAlarm(t); },        // 切断の猶予(再接続)の期限
        deleteAlarm: () => { this.ctx.storage.deleteAlarm(); },
      }, games);
      // 生存確認の "ping" には、Durable Object を起こさずに "pong" を返す
      this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
    }

    async fetch(request) {
      const url = new URL(request.url);
      // clientKey: 接続元の見分け(入室失敗の制限 rooms.joinLimit 用)。Cloudflare が付ける接続元 IP を、サーバー側だけが持つ salt でハッシュにしたもの
      // (生の IP は、保存しない)。入室失敗の記録は、最後の失敗から1時間で消える。非同期の計算は、接続を受け付ける前に済ませる。
      let salt = this.ctx.storage.kv.get("salt");
      if (!salt) { salt = crypto.randomUUID(); this.ctx.storage.kv.put("salt", salt); }
      const clientKey = await hashClientKey(request.headers.get("CF-Connecting-IP"), salt);
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server);
      this.core.onOpen(server, {
        game: url.searchParams.get("game"), v: url.searchParams.get("v") ?? undefined,
        clientKey,
      });
      return new Response(null, { status: 101, webSocket: client });
    }

    alarm() {
      this.core.onAlarm();
    }

    webSocketMessage(ws, message) {
      this.core.onMessage(ws, message);
    }

    webSocketClose(ws, code) {
      this.core.onClose(ws);
      try { ws.close(code >= 1000 && code < 1005 ? code : 1000, "bye"); } catch (_) { /* すでに閉じている */ }
    }

    webSocketError(ws) {
      this.core.onClose(ws);
    }
  }

  const handler = {
    async fetch(request, env) {
      const url = new URL(request.url);
      if (url.pathname !== "/ws") return new Response("Not found", { status: 404 });
      if (request.headers.get("Upgrade") !== "websocket") return new Response("Expected a WebSocket", { status: 426 });
      // 別のサイトのページからの接続は断る(ブラウザ以外は Origin なしで来るので通す)
      const origin = request.headers.get("Origin");
      if (origin) {
        const host = new URL(origin).hostname;
        if (host !== url.hostname && host !== "localhost" && host !== "127.0.0.1") {
          return new Response("Forbidden", { status: 403 });
        }
      }
      return env[binding].get(env[binding].idFromName(instance)).fetch(request);
    },
  };
  return { Hub, handler };
}
