// Python クライアントの適合テスト用のホスト。標準入力の1行(JSON)= 1命令を、世界(world.mjs)に実行して、
// サーバーから出たもの({"c": 接続ID, "m": メッセージ} / {"c":…, "closed": コード})を1行ずつ出力し、最後に {"ack": 番号} を返す。
//   命令: {"n":1,"op":"open","c":"p1","game":"cards","v":2} / say(c,text) / close(c) / tick(ms) / alarm
import { createInterface } from "node:readline";
import { makeWorld } from "./world.mjs";

const world = makeWorld();
const emit = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const ids = new Set();
const attach = (c) => { if (!ids.has(c)) { ids.add(c); world.attach(c, (o) => emit({ c, ...o })); } };

createInterface({ input: process.stdin }).on("line", (line) => {
  const cmd = JSON.parse(line);
  if (cmd.c) attach(cmd.c);
  if (cmd.op === "open") world.open(cmd.c, cmd.game, cmd.v);
  else if (cmd.op === "say") world.say(cmd.c, cmd.text);
  else if (cmd.op === "close") world.close(cmd.c);
  else if (cmd.op === "tick") world.tick(cmd.ms);
  else if (cmd.op === "alarm") world.alarm();
  emit({ ack: cmd.n });
});
