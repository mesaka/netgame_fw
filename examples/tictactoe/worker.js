// ○×のサーバー(ローカル確認用の入口): npx wrangler dev -c examples/tictactoe/wrangler.jsonc
import { createGameWorker } from "../../server/worker.js";
import tictactoe from "./adapter.js";

const { Hub, handler } = createGameWorker({ tictactoe });
export { Hub };
export default handler;
