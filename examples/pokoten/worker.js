// ポコテンのサーバー(ローカル確認用の入口)。本物の入口は、ポコテン側のリポジトリに置く。
import { createGameWorker } from "../../server/worker.js";
import pokoten from "./adapter.js";

const { Hub, handler } = createGameWorker({ pokoten });
export { Hub };
export default handler;
