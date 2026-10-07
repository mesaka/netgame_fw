// 数当て(3人)のサーバー側アダプター。turns 方式で、3人の部屋(席・名簿・手番の巡り・ハッシュ・結果)を確かめるための見本。
// ルール(クライアント側): 秘密の数(1〜100)を、seed から全員が同じに作る。席の順に数を言い、近い順に順位がつく(同じ距離は同順位)。
// 3人以上の途中退出の扱い(続行など)は、保留。いまは、対戦が中止になる(why: "abort")。
export default {
  id: "guess3",
  mode: "turns",
  minPlayers: 3,
  maxPlayers: 3,
  matchKey: () => "all",
  turns: {
    maxActionBytes: 32,
    validate: (_room, _seat, d) => d && Number.isInteger(d.n) && d.n >= 1 && d.n <= 100,
  },
};
