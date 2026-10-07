// Cloudflare Worker の入口。/ws だけをこの Worker が受け持つ(wrangler.jsonc の run_worker_first)。
import { createGameWorker } from "./netgame/worker.js";
import mygame from "./adapter.js";

const { Hub, handler } = createGameWorker({ mygame });     // 複数のゲームを同じサーバーに載せるなら、{ a, b } と並べる
export { Hub };                                            // wrangler.jsonc の class_name と同じ名前
export default handler;
