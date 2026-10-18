/** Same normalisation as the server: Cyrillic and Latin Uzbek/Russian compare equal. */
const CYR: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "j", з: "z", и: "i", й: "y", к: "k",
  л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "x", ц: "ts",
  ч: "ch", ш: "sh", щ: "sh", ъ: "", ы: "i", ь: "", э: "e", ю: "yu", я: "ya", ў: "o", қ: "q", ғ: "g", ҳ: "h",
};
const APOSTROPHES = /['`ʻʼ‘’]/g;

export function normalize(text: string): string {
  let out = "";
  for (const ch of (text || "").toLowerCase().replace(APOSTROPHES, "")) out += CYR[ch] ?? ch;
  return out.split(/\s+/).filter(Boolean).join(" ");
}
