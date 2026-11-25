"""Static analysis of SPL detection queries.

This is a dependency extractor, not a full SPL parser. It answers: which indexes, sourcetypes and raw event
fields does this rule depend on, which commands does it use, and what numeric thresholds does it apply?

Anything it cannot interpret (macros, subsearches, lookups, unknown commands) is reported in
``SplAnalysis.unparsed`` instead of being guessed. Callers should treat a non-empty ``unparsed`` as
"dependencies may be incomplete".
"""

from __future__ import annotations

import contextlib
import re

from logops.models import SplAnalysis, Threshold

# Commands after which field names refer to aggregated rows, not raw events.
TRANSFORMING = frozenset({"stats", "chart", "timechart", "tstats", "top", "rare", "transaction"})
STATS_LIKE = frozenset({"stats", "eventstats", "streamstats", "chart", "timechart", "tstats"})
FILTERING = frozenset({"search", "where"})
HARMLESS = frozenset({"head", "tail", "table", "fields", "sort", "reverse", "fillnull", "bin", "bucket"})
UNANALYZED = frozenset(
    {"lookup", "inputlookup", "join", "append", "appendcols", "map", "rex", "spath", "multisearch"}
)

_CMP_OPS = r"(?:!=|<=|>=|==|=|<|>)"
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_TOKEN_RE = re.compile(
    rf"""\s*(?:
        (?P<quoted>{_QUOTED})
      | (?P<paren>[()])
      | (?P<cmp>(?P<key>[A-Za-z_][\w.:\-]*)\s*(?P<op>{_CMP_OPS})\s*(?P<val>{_QUOTED}|[^\s()]+))
      | (?P<word>[^\s()]+)
    )""",
    re.VERBOSE,
)
_THRESHOLD_RE = re.compile(rf"\b([A-Za-z_][\w.]*)\s*({_CMP_OPS})\s*(-?\d+(?:\.\d+)?)\b")
_AGG_RE = re.compile(
    r"(?P<func>[A-Za-z_]\w*)(?:\((?P<arg>[^)]*)\))?(?:\s+as\s+(?P<alias>[A-Za-z_][\w.]*))?", re.IGNORECASE
)
_IDENT_RE = re.compile(r"[A-Za-z_][\w.]*")
_KEYWORDS = frozenset({"and", "or", "not", "as", "by", "over", "like", "in", "true", "false", "null"})


def split_pipeline(spl: str) -> tuple[list[str], bool]:
    """Split on top-level pipes, ignoring pipes inside quotes or ``[...]`` subsearches.

    Returns (segments, has_subsearch). The first segment is the base search ("" when the query
    starts with a generating command such as ``| tstats``).
    """
    segments: list[str] = []
    buf: list[str] = []
    depth = 0
    in_quote = False
    escaped = False
    has_sub = False
    for ch in spl:
        if in_quote:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_quote = False
            continue
        if ch == '"':
            in_quote = True
        elif ch == "[":
            depth += 1
            has_sub = True
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "|" and depth == 0:
            segments.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    segments.append("".join(buf).strip())
    return segments, has_sub


def _strip_subsearches(text: str) -> str:
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


class _Collector:
    def __init__(self) -> None:
        self.indexes: dict[str, None] = {}
        self.sourcetypes: dict[str, None] = {}
        self.filter_fields: dict[str, None] = {}
        self.group_by: dict[str, None] = {}
        self.aggregate: dict[str, None] = {}
        self.derived: dict[str, None] = {}
        self.commands: list[str] = []
        self.thresholds: list[Threshold] = []
        self.unparsed: list[str] = []
        self.transformed = False

    def search_terms(self, text: str) -> None:
        """Interpret ``key=value`` terms of a base search, a ``search`` command or a ``tstats where`` clause."""
        if "`" in text:
            self.unparsed.append("macro")
            text = re.sub(r"`[^`]*`", " ", text)
        for m in _TOKEN_RE.finditer(text):
            if not m.group("cmp"):
                continue
            key, op, val = m.group("key"), m.group("op"), m.group("val").strip('"')
            low = key.lower()
            if low == "index" and op in ("=", "=="):
                self.indexes.setdefault(val, None)
            elif low == "sourcetype" and op in ("=", "=="):
                self.sourcetypes.setdefault(val, None)
            elif low in ("index", "sourcetype", "source", "host"):
                continue
            elif self.transformed:
                self._threshold(key, op, val)
            else:
                self.filter_fields.setdefault(key, None)

    def _threshold(self, key: str, op: str, val: str) -> None:
        with contextlib.suppress(ValueError):
            self.thresholds.append(Threshold(field=key, op=op, value=float(val)))

    def where(self, text: str) -> None:
        for fld, op, num in _THRESHOLD_RE.findall(text):
            self.thresholds.append(Threshold(field=fld, op=op, value=float(num)))
        if self.transformed:
            return
        stripped = re.sub(_QUOTED, " ", text)
        for ident in _IDENT_RE.findall(stripped):
            low = ident.lower()
            if low in _KEYWORDS or ident in self.derived or "(" in ident:
                continue
            # function names such as like(...) or isnull(...)
            if re.search(rf"\b{re.escape(ident)}\s*\(", stripped):
                continue
            self.filter_fields.setdefault(ident, None)

    def stats(self, cmd: str, text: str) -> None:
        body = text
        if cmd == "tstats":
            # tstats [aggs] [from datamodel=X] [where <search>] [by ...]
            m = re.search(r"\bwhere\b(.*?)(?=\bby\b|$)", body, re.IGNORECASE | re.DOTALL)
            if m:
                self.search_terms(m.group(1))
                body = body[: m.start()] + " " + body[m.end() :]
            if re.search(r"\bfrom\s+datamodel", body, re.IGNORECASE):
                self.unparsed.append("tstats datamodel")
        by_split = re.split(r"\bby\b", body, maxsplit=1, flags=re.IGNORECASE)
        aggs = re.sub(r"\b\w+=\S+", " ", by_split[0])  # drop options such as span=1h
        for m in _AGG_RE.finditer(aggs):
            func, arg, alias = m.group("func"), m.group("arg"), m.group("alias")
            if func.lower() in _KEYWORDS:
                continue
            if arg is not None:
                for raw in re.split(r"[,\s]+", arg.strip()):
                    if raw and _IDENT_RE.fullmatch(raw) and not self.transformed:
                        self.aggregate.setdefault(raw, None)
                self.derived.setdefault(alias or f"{func}({arg})", None)
            else:
                self.derived.setdefault(alias or func, None)
        if len(by_split) == 2:
            for raw in re.split(r"[,\s]+", by_split[1].strip()):
                if (
                    raw
                    and _IDENT_RE.fullmatch(raw)
                    and raw.lower() not in _KEYWORDS
                    and "=" not in raw
                    and not self.transformed
                ):
                    self.group_by.setdefault(raw, None)
        if cmd in TRANSFORMING:
            self.transformed = True

    def eval(self, text: str) -> None:
        for m in re.finditer(r"([A-Za-z_][\w.]*)\s*=(?!=)", text):
            self.derived.setdefault(m.group(1), None)

    def rename(self, text: str) -> None:
        for src, dst in re.findall(r"([\w.*]+)\s+as\s+([\w.*]+)", text, re.IGNORECASE):
            if not self.transformed:
                self.filter_fields.setdefault(src, None)
            self.derived.setdefault(dst, None)

    def dedup(self, text: str) -> None:
        if self.transformed:
            return
        for raw in re.split(r"[,\s]+", text.strip()):
            if raw and _IDENT_RE.fullmatch(raw) and "=" not in raw:
                self.filter_fields.setdefault(raw, None)

    def result(self) -> SplAnalysis:
        return SplAnalysis(
            indexes=tuple(self.indexes),
            sourcetypes=tuple(self.sourcetypes),
            filter_fields=tuple(self.filter_fields),
            group_by_fields=tuple(self.group_by),
            aggregate_fields=tuple(self.aggregate),
            derived_fields=tuple(self.derived),
            commands=tuple(self.commands),
            thresholds=tuple(self.thresholds),
            unparsed=tuple(dict.fromkeys(self.unparsed)),
        )


def analyze(spl: str) -> SplAnalysis:
    """Extract dependencies from an SPL query. Never raises on odd input; reports it in ``unparsed``."""
    segments, has_sub = split_pipeline(spl.strip())
    c = _Collector()
    if has_sub:
        c.unparsed.append("subsearch")

    base = _strip_subsearches(segments[0])
    if base:
        if base.lower().startswith("search "):
            base = base[7:]
        c.search_terms(base)

    for seg in segments[1:]:
        seg = _strip_subsearches(seg)
        if not seg:
            continue
        parts = seg.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        c.commands.append(cmd)
        if cmd == "search":
            c.search_terms(rest)
        elif cmd == "where":
            c.where(rest)
        elif cmd in STATS_LIKE:
            c.stats(cmd, rest)
        elif cmd in ("top", "rare"):
            c.stats(cmd, f"count by {rest}")
        elif cmd == "eval":
            c.eval(rest)
        elif cmd == "rename":
            c.rename(rest)
        elif cmd == "dedup":
            c.dedup(rest)
        elif cmd in HARMLESS:
            continue
        elif cmd in UNANALYZED:
            c.unparsed.append(f"command:{cmd}")
        else:
            c.unparsed.append(f"command:{cmd}")
    return c.result()
