"""Small text helpers shared by every extractor.

Extraction is regular expressions over source text. That is the right tool for
mapping call sites - we are locating bindings, not type-checking a program -
but it needs guardrails: do not match inside a comment, do not miss a topic
name that sits two lines below the call that uses it, and produce stable ids.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #

_SLUG_STRIP = re.compile(r"[^a-zA-Z0-9._\-]+")
_SLUG_EDGES = re.compile(r"^[-._]+|[-._]+$")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def slugify(value: str, keep_dots: bool = True) -> str:
    """Stable, filesystem-safe, still human-readable id."""
    text = _CAMEL_BOUNDARY.sub("-", str(value or "").strip())
    text = text.replace("_", "-").replace(" ", "-").replace("/", "-")
    text = _SLUG_STRIP.sub("-", text)
    if not keep_dots:
        text = text.replace(".", "-")
    text = re.sub(r"-{2,}", "-", text)
    return _SLUG_EDGES.sub("", text).lower() or "unnamed"


def topic_id(value: str) -> str:
    """Topic ids keep their real punctuation: `orders.created`, `orders-dlq`."""
    text = str(value or "").strip().strip("\"'`")
    text = _SLUG_STRIP.sub("-", text)
    return _SLUG_EDGES.sub("", text) or "unnamed-topic"


def safe_filename(value: str) -> str:
    return slugify(value, keep_dots=False)


# --------------------------------------------------------------------------- #
# String literals and config references
# --------------------------------------------------------------------------- #

_STRING_LITERAL = re.compile(
    r"""(?P<q>["'`])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)""",
    re.DOTALL,
)

# ${app.topics.orders}   ${ORDERS_TOPIC:-orders.created}   ${ORDERS_TOPIC:def}
_PLACEHOLDER = re.compile(r"\$\{\s*([A-Za-z0-9_.\-]+)\s*(?::-?([^}]*))?\}")

_ENV_REFERENCE = re.compile(
    r"""(?:
        os\.environ(?:\.get)?\s*[\[(]\s*["'](?P<a>[A-Za-z0-9_]+)["']
      | os\.getenv\s*\(\s*["'](?P<b>[A-Za-z0-9_]+)["']
      | process\.env\.(?P<c>[A-Za-z0-9_]+)
      | process\.env\[\s*["'](?P<d>[A-Za-z0-9_]+)["']\s*\]
      | os\.Getenv\s*\(\s*["'](?P<e>[A-Za-z0-9_]+)["']\s*\)
      | System\.getenv\s*\(\s*["'](?P<f>[A-Za-z0-9_]+)["']\s*\)
      | ENV\[\s*["'](?P<g>[A-Za-z0-9_]+)["']\s*\]
    )""",
    re.VERBOSE,
)


class Literal(object):
    """A call argument, resolved to a value or still pointing at a symbol.

    `resolved` is the whole point: a resolved literal can support a `[CODE]`
    edge, an unresolved one cannot until the config index resolves the symbol.
    """

    __slots__ = ("value", "resolved", "origin", "raw")

    def __init__(self, value: str, resolved: bool, origin: str = "", raw: str = "") -> None:
        self.value = value
        self.resolved = resolved
        self.origin = origin        # literal | placeholder:KEY | env:KEY | symbol:NAME
        self.raw = raw

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Literal({0!r}, resolved={1}, origin={2!r})".format(
            self.value, self.resolved, self.origin)


def first_string_literal(text: str) -> Optional[str]:
    match = _STRING_LITERAL.search(text)
    return match.group("body") if match else None


def all_string_literals(text: str) -> List[str]:
    return [m.group("body") for m in _STRING_LITERAL.finditer(text)]


def extract_argument(text: str) -> Optional[Literal]:
    """Best-effort read of the first meaningful argument in `text`.

    Order matters. A string literal wins. Failing that we report the config key
    or environment variable we saw, so the caller can try to resolve it against
    the config index before deciding the edge is only an inference.
    """
    literal = first_string_literal(text)
    if literal is not None and literal.strip():
        placeholder = _PLACEHOLDER.search(literal)
        if placeholder:
            key, default = placeholder.group(1), placeholder.group(2)
            if default:
                return Literal(default, True, "placeholder:" + key, literal)
            return Literal(key, False, "placeholder:" + key, literal)
        return Literal(literal, True, "literal", literal)

    env = _ENV_REFERENCE.search(text)
    if env:
        name = next(value for value in env.groups() if value)
        return Literal(name, False, "env:" + name, env.group(0))

    dotted = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)", text)
    if dotted:
        return Literal(dotted.group(1), False, "symbol:" + dotted.group(1), dotted.group(1))

    shouty = re.search(r"\b([A-Z][A-Z0-9_]{2,})\b", text)
    if shouty:
        return Literal(shouty.group(1), False, "symbol:" + shouty.group(1), shouty.group(1))
    return None


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #

_LINE_COMMENT_MARKERS = {
    ".py": ("#",), ".rb": ("#",), ".sh": ("#",), ".yaml": ("#",), ".yml": ("#",),
    ".tf": ("#",), ".tfvars": ("#",), ".properties": ("#", "!"), ".env": ("#",),
    ".java": ("//",), ".kt": ("//",), ".kts": ("//",), ".scala": ("//",),
    ".go": ("//",), ".js": ("//",), ".jsx": ("//",), ".ts": ("//",),
    ".tsx": ("//",), ".mjs": ("//",), ".cjs": ("//",), ".cs": ("//",),
    ".proto": ("//",), ".rs": ("//",), ".php": ("//", "#"),
}


def strip_comment(line: str, suffix: str) -> str:
    """Drop a trailing line comment without eating `https://` inside a string."""
    markers = _LINE_COMMENT_MARKERS.get(suffix, ("#", "//"))
    in_string = None  # type: Optional[str]
    index = 0
    while index < len(line):
        char = line[index]
        if in_string is not None:
            if char == "\\":
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "\"'`":
            in_string = char
        else:
            for marker in markers:
                if line.startswith(marker, index):
                    return line[:index]
        index += 1
    return line


# --------------------------------------------------------------------------- #
# Multi-line windows and argument splitting
# --------------------------------------------------------------------------- #

def window(lines: List[str], index: int, span: int = 3, suffix: str = "") -> str:
    """Join `span` lines from `index`, so a call that wraps still matches.

        kafkaTemplate.send(
            "orders.created", key, payload);

    is one logical call. The anchor is at `index`; the topic is below it.
    """
    chunk = lines[index:index + span]
    if suffix:
        chunk = [strip_comment(line, suffix) for line in chunk]
    return " ".join(part.strip() for part in chunk)


def balanced_call_args(text: str, open_at: int) -> str:
    """The argument text between the bracket at `open_at` and its partner."""
    if open_at < 0 or open_at >= len(text):
        return ""
    depth = 0
    in_string = None  # type: Optional[str]
    for index in range(open_at, len(text)):
        char = text[index]
        if in_string is not None:
            if char == "\\":
                continue
            if char == in_string:
                in_string = None
            continue
        if char in "\"'`":
            in_string = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:index]
    return text[open_at + 1:]


def split_args(text: str) -> List[str]:
    """Split call arguments on top-level commas only."""
    parts = []  # type: List[str]
    current = []  # type: List[str]
    depth = 0
    in_string = None  # type: Optional[str]
    index = 0
    while index < len(text):
        char = text[index]
        if in_string is not None:
            current.append(char)
            if char == "\\" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "\"'`":
            in_string = char
            current.append(char)
        elif char in "([{":
            depth += 1
            current.append(char)
        elif char in ")]}":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def paren_after(text: str, pattern: "re.Pattern") -> int:
    """Index of the bracket opening the call `pattern` matched, or -1."""
    match = pattern.search(text)
    if not match:
        return -1
    return text.find("(", match.start())


def truncate(value: str, limit: int = 64) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit - 1] + "..."


def line_of(lines: List[str], needle: str, default: int = 1) -> int:
    """1-based line number where `needle` first appears."""
    if not needle:
        return default
    for number, line in enumerate(lines, start=1):
        if needle in line:
            return number
    return default
