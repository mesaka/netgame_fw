import { createGameWorker } from "../../server/worker.js";
import cards from "./adapter.js";

const { Hub, handler } = createGameWorker({ cards });
export { Hub };
export default handler;
