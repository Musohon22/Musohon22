import type { Lang } from "../types";
import { en } from "./en";
import { ru } from "./ru";
import { uz, type MessageKey } from "./uz";

export type { MessageKey };
export type Vars = Record<string, string | number>;

const APOS = "'ʻʼ‘’`";
const DIGRAPHS: [string, string][] = [
  ["o'", "ў"], ["g'", "ғ"], ["sh", "ш"], ["ch", "ч"], ["yo", "ё"], ["yu", "ю"], ["ya", "я"], ["ye", "е"],
];
const SINGLE: Record<string, string> = {
  a: "а", b: "б", d: "д", f: "ф", g: "г", h: "ҳ", i: "и", j: "ж", k: "к", l: "л", m: "м", n: "н",
  o: "о", p: "п", q: "қ", r: "р", s: "с", t: "т", u: "у", v: "в", x: "х", y: "й", z: "з",
};

function withCase(src: string, out: string) {
  return src[0] === src[0].toUpperCase() && src[0] !== src[0].toLowerCase()
    ? out[0].toUpperCase() + out.slice(1)
    : out;
}

/** Uzbek Latin → Uzbek Cyrillic, leaving {placeholders} untouched. */
export function toCyrillic(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "{") {
      const end = text.indexOf("}", i);
      if (end > i) {
        out += text.slice(i, end + 1);
        i = end + 1;
        continue;
      }
    }
    const pair = (text[i] + (text[i + 1] ?? "")).toLowerCase().replace(/[ʻʼ‘’`]/, "'");
    const digraph = DIGRAPHS.find(([lat]) => lat === pair);
    if (digraph) {
      out += withCase(ch, digraph[1]);
      i += 2;
      continue;
    }
    const lower = ch.toLowerCase();
    if (lower === "e") {
      const prev = text[i - 1];
      const wordStart = !prev || !/[A-Za-zʻʼ‘’'`]/.test(prev);
      out += withCase(ch, wordStart ? "э" : "е");
    } else if (APOS.includes(ch) && i > 0 && /[A-Za-z]/.test(text[i - 1] ?? "") && /[A-Za-z]/.test(text[i + 1] ?? "")) {
      out += "ъ";
    } else if (SINGLE[lower]) {
      out += withCase(ch, SINGLE[lower]);
    } else {
      out += ch;
    }
    i++;
  }
  return out;
}

const cyrillicCache = new Map<MessageKey, string>();

function lookup(lang: Lang, key: MessageKey): string {
  if (lang === "ru") return ru[key];
  if (lang === "en") return en[key];
  if (lang === "uz-Cyrl") {
    let v = cyrillicCache.get(key);
    if (v === undefined) {
      v = toCyrillic(uz[key]);
      cyrillicCache.set(key, v);
    }
    return v;
  }
  return uz[key];
}

export function translate(lang: Lang, key: MessageKey, vars?: Vars): string {
  let text = lookup(lang, key) ?? uz[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) text = text.split(`{${k}}`).join(String(v));
  }
  return text;
}

export function hasKey(key: string): key is MessageKey {
  return key in uz;
}

/** Message for an API error code, falling back to a generic one. */
export function errorKey(code: string): MessageKey {
  const key = `err.${code}`;
  return hasKey(key) ? key : "err.unknown";
}

export const LANGS: { value: Lang; label: string }[] = [
  { value: "uz", label: "O'zbekcha" },
  { value: "uz-Cyrl", label: "Ўзбекча" },
  { value: "ru", label: "Русский" },
  { value: "en", label: "English" },
];

export const INTL_LOCALE: Record<Lang, string> = { uz: "uz-Latn-UZ", "uz-Cyrl": "uz-Cyrl-UZ", ru: "ru-RU", en: "en-GB" };
