// ○×(2人)のサーバー側アダプター。turns(ロックステップ)方式の見本。
// ルールはクライアントだけにある。サーバーは、手番(席の順)・通し番号・ハッシュの突き合わせ・結果の一致の確認だけをやる。
export default {
  id: "tictactoe",
  mode: "turns",
  minPlayers: 2,
  maxPlayers: 2,
  matchKey: () => "all",                 // 設定なし。ランダムマッチは、待っている人どうし
  turns: {
    maxActionBytes: 64,
    // 手の形だけ確かめる(マスが空いているかは、ルールを持つクライアントが決める。空いていない手は、全員が同じく無視する)
    validate: (_room, _seat, d) => d && Number.isInteger(d.cell) && d.cell >= 0 && d.cell <= 8,
  },
};
