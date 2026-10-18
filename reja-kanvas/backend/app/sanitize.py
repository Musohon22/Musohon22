"""Allowlist HTML sanitizer for rich-text plan bodies (what the TipTap editor produces).

Anything not listed is dropped; text inside dropped tags is kept, except for tags whose
content is never safe to show (scripts, styles, embeds)."""

import html
import re
from html.parser import HTMLParser

ALLOWED: dict[str, set[str]] = {
    "p": set(), "br": set(), "hr": set(), "div": set(),
    "h1": set(), "h2": set(), "h3": set(),
    "strong": set(), "b": set(), "em": set(), "i": set(), "u": set(), "s": set(),
    "code": set(), "pre": set(), "blockquote": set(),
    "ul": {"data-type"}, "ol": {"start"}, "li": {"data-type", "data-checked"},
    "a": {"href", "target", "rel"},
    "mark": {"data-color", "style"}, "span": {"style"},
    "label": set(), "input": {"type", "checked", "disabled"},
}
VOID = {"br", "hr", "input"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "head", "title"}

_SAFE_HREF = re.compile(r"^(https?:|mailto:)", re.I)
_SAFE_COLOR = re.compile(r"^(#[0-9a-f]{3,8}|rgba?\(\s*[\d.\s,%]+\)|[a-z]{3,20})$", re.I)
_STYLE_PROPS = {"color", "background-color"}


def _clean_style(value: str) -> str | None:
    kept = []
    for decl in value.split(";"):
        if ":" not in decl:
            continue
        prop, val = (p.strip().lower() for p in decl.split(":", 1))
        if prop in _STYLE_PROPS and _SAFE_COLOR.match(val):
            kept.append(f"{prop}: {val}")
    return "; ".join(kept) or None


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            if tag not in VOID:
                self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED:
            return
        clean = []
        for name, value in attrs:
            if name not in ALLOWED[tag]:
                continue
            value = value or ""
            if name == "href":
                if not _SAFE_HREF.match(value.strip()):
                    continue
            elif name == "style":
                value = _clean_style(value)
                if value is None:
                    continue
            elif name == "type" and value != "checkbox":
                continue
            elif name == "target":
                value = "_blank"
            clean.append((name, value))
        if tag == "a":
            clean = [a for a in clean if a[0] != "rel"] + [("rel", "noopener noreferrer nofollow")]
        if tag == "input" and ("type", "checkbox") not in clean:
            return
        rendered = "".join(
            f' {n}="{html.escape(v, quote=True)}"' if v != "" else f" {n}" for n, v in clean
        )
        self.out.append(f"<{tag}{rendered}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth or tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.out.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(value: str) -> str:
    parser = _Sanitizer()
    parser.feed(value or "")
    parser.close()
    return parser.result()


def html_to_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()
