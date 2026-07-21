/**
 * 🔑 Client-side password utilities (v1.8.0)
 *
 * generatePassword — CSPRNG-backed (crypto.getRandomValues), so generated
 * passwords are as strong as the browser allows: 16 chars by default with a
 * guaranteed mix of lower/upper/digit/symbol, unbiased modulo via rejection
 * sampling, then Fisher–Yates shuffled so position never leaks the rule.
 */
const LOWER = "abcdefghijkmnopqrstuvwxyz"; // no 'l' — visually ambiguous
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"; // no 'I','O'
const DIGIT = "23456789"; // no '0','1'
const SYMBOL = "!@#$%^&*()-_=+[]{}<>?";
const ALL = LOWER + UPPER + DIGIT + SYMBOL;

function cryptoInt(maxExclusive: number): number {
  // rejection sampling → unbiased
  const buf = new Uint32Array(1);
  const limit = Math.floor(0x100000000 / maxExclusive) * maxExclusive;
  let v: number;
  do {
    crypto.getRandomValues(buf);
    v = buf[0];
  } while (v >= limit);
  return v % maxExclusive;
}

function pick(set: string): string {
  return set[cryptoInt(set.length)];
}

export function generatePassword(len = 16): string {
  const n = Math.max(8, Math.min(len, 64));
  const chars: string[] = [pick(LOWER), pick(UPPER), pick(DIGIT), pick(SYMBOL)];
  while (chars.length < n) chars.push(pick(ALL));
  // Fisher–Yates with CSPRNG
  for (let i = chars.length - 1; i > 0; i--) {
    const j = cryptoInt(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

/** quick label for the strength hint under the new-password field */
export function passwordStrength(pw: string): { score: 0 | 1 | 2 | 3 | 4; label: string; cls: string } {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 14) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const capped = Math.min(4, Math.max(0, score - (pw.length < 8 ? 1 : 0))) as 0 | 1 | 2 | 3 | 4;
  const map = [
    { label: "very weak", cls: "text-red-400" },
    { label: "weak", cls: "text-orange-400" },
    { label: "okay", cls: "text-yellow-400" },
    { label: "strong", cls: "text-emerald-400" },
    { label: "excellent", cls: "text-emerald-300" },
  ] as const;
  return { score: capped, ...map[capped] };
}
