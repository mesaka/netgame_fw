// 文字列の整形(Cloudflare に依存しない)。

/** 制御文字を除き、前後の空白を削り、最大 max 文字(コードポイント)に切る。 */
export function cleanText(s, max) {
  if (typeof s !== "string") return "";
  const t = s.replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, "").trim();
  return Array.from(t).slice(0, max).join("");
}

/** 整数なら範囲に収める。そうでなければ lo。 */
export function clampInt(v, lo, hi) {
  return Math.max(lo, Math.min(hi, Math.trunc(Number(v)) || 0));
}
