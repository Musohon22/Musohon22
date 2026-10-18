"""Search normalisation: Uzbek/Russian Cyrillic and Latin text map to one comparable form,
so "режа" finds "reja" and "O‘qish" finds "oqish"."""

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}
_APOSTROPHES = "'`ʻʼ‘’"


def normalize(text: str) -> str:
    out = []
    for ch in (text or "").lower():
        if ch in _APOSTROPHES:
            continue
        out.append(_CYR.get(ch, ch))
    return " ".join("".join(out).split())
