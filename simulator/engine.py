"""Deterministic simulated Splunk backend.

Given a scenario, a seed and a fixed "now" (injectable), it generates events and answers the six gateway ops.
``run_search`` evaluates a documented SPL subset (see "Simulator SPL subset" in ``docs/ARCHITECTURE.md``):

* anything outside the subset raises ``SimError("unsupported", ...)``. The simulator never guesses;
* SPL the simulator can prove malformed (unbalanced quotes, a comparison with no value, an unknown stats
  function, ...) raises ``SimError("search_error", ...)``, which the gateway turns into ``SearchError``.

Pipelines are split with ``logops.spl.split_pipeline``. Results reuse the ``logops.models`` shapes.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from logops.models import (
    FieldStat,
    FieldSummary,
    IndexInfo,
    SavedSearch,
    SchedulerRun,
    SearchResult,
    SourcetypeStats,
)
from logops.spl import split_pipeline
from simulator.scenario import Scenario, SourcetypeSpec, parse_duration

Event = dict[str, Any]
Row = dict[str, Any]

DEFAULT_INDEX = "main"
"""A search with no ``index`` term searches only this index (Splunk's default for most roles)."""


class SimError(Exception):
    """A structured simulator error. ``kind`` is part of the wire contract (see ``sim.toml``)."""

    KINDS = frozenset({"search_error", "unsupported", "invalid_argument", "auth", "unavailable"})

    def __init__(self, kind: str, message: str) -> None:
        if kind not in self.KINDS:
            raise ValueError(f"unknown SimError kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.message = message


def _unsupported(what: str) -> SimError:
    return SimError("unsupported", f"not supported by the LogOps simulator: {what}")


def _syntax(what: str) -> SimError:
    return SimError("search_error", f"Error in search: {what}")


# --------------------------------------------------------------------------- time


_REL_RE = re.compile(r"^-(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days|w|week|weeks)$")
_REL_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
}


def parse_time(text: str, now: datetime) -> datetime | None:
    """Splunk-style time modifier → absolute time. ``None`` means unbounded (``0`` / empty earliest).

    Supported: ``now``, ``0``, ``-<n><unit>``, epoch seconds, ISO 8601. Snap-to (``@d``) is unsupported.
    """
    t = text.strip()
    if t in ("", "0"):
        return None
    if t == "now":
        return now
    if "@" in t:
        raise _unsupported(f"time snapping {text!r}")
    m = _REL_RE.match(t)
    if m:
        return now - timedelta(seconds=int(m.group(1)) * _REL_UNITS[m.group(2)])
    if re.fullmatch(r"\d+(\.\d+)?", t):
        return datetime.fromtimestamp(float(t), tz=UTC)
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise SimError("invalid_argument", f"invalid time modifier {text!r}") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- event generation

_SECURITY_ACTIONS = ("failed_login", "failed_login", "failed_login", "success_login")
_SECURITY_USERS = ("admin", "root", "deploy_user", "jenkins", "backup_svc")
_DB_ACTIONS = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE TABLE", "DROP TABLE")
_DB_TABLES = ("users", "orders", "products", "sessions", "audit_log", "config")
_DB_USERS = ("app_user", "admin", "read_only", "backup_svc", "analytics")


def _ip(rng: random.Random, prefix: str = "192.168") -> str:
    parts = prefix.split(".")
    while len(parts) < 4:
        parts.append(str(rng.randint(1, 255)))
    return ".".join(parts)


def _builtin_fields(kind: str, rng: random.Random) -> dict[str, Any]:
    """Event shapes ported from the v1 ``log_generator.py``."""
    if kind == "security":
        return {
            "action": rng.choice(_SECURITY_ACTIONS),
            "src_ip": _ip(rng),
            "user": rng.choice(_SECURITY_USERS),
            "log_type": "security",
        }
    if kind == "database":
        return {
            "action": rng.choice(_DB_ACTIONS),
            "table": rng.choice(_DB_TABLES),
            "user": rng.choice(_DB_USERS),
            "src_ip": _ip(rng),
            "rows_affected": rng.randint(1, 100),
            "duration_ms": rng.randint(10, 500),
            "log_type": "database",
        }
    return {}


def generate_events(seed: int, index: str, spec: SourcetypeSpec, now: datetime) -> list[Event]:
    """Deterministic for a given (seed, index, sourcetype, now). Newest first, whole seconds."""
    rng = random.Random(f"{seed}:{index}:{spec.name}")
    newest = now.replace(microsecond=0) - parse_duration(spec.lag)
    oldest = now.replace(microsecond=0) - parse_duration(spec.span)
    total = (newest - oldest).total_seconds()
    events: list[Event] = []
    for i in range(spec.count):
        frac = 0.0 if spec.count == 1 else i / (spec.count - 1)
        t = newest - timedelta(seconds=int(total * frac))
        fields = _builtin_fields(spec.generator, rng)
        for name, gen in spec.fields.items():
            if gen.value is not None:
                fields[name] = gen.value
            elif gen.choices is not None:
                fields[name] = rng.choice(gen.choices)
            elif gen.ip_prefix is not None:
                fields[name] = _ip(rng, gen.ip_prefix)
            elif gen.int_range is not None:
                fields[name] = rng.randint(*gen.int_range)
        for old, new in spec.rename_fields.items():
            if old in fields:
                fields[new] = fields.pop(old)
        for name in spec.drop_fields:
            fields.pop(name, None)
        if spec.generator != "custom":
            fields["timestamp"] = _iso(t)
        event: Event = dict(fields)
        event.update(
            {
                "_time": t,
                "_raw": json.dumps(fields, sort_keys=True),
                "index": index,
                "sourcetype": spec.name,
                "host": spec.host,
                "source": spec.source or f"sim:{spec.name}",
            }
        )
        events.append(event)
    return events


# --------------------------------------------------------------------------- SPL tokenizer

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<quoted>"(?:[^"\\]|\\.)*")
      | (?P<paren>[(),])
      | (?P<op>==|!=|<=|>=|=|<|>)
      | (?P<word>[^\s()=!<>,"]+)
      | (?P<bad>["!])
    )""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class Tok:
    kind: str  # quoted | paren | op | word
    text: str

    @property
    def value(self) -> str:
        if self.kind == "quoted":
            return re.sub(r"\\(.)", r"\1", self.text[1:-1])
        return self.text

    def is_kw(self, kw: str) -> bool:
        return self.kind == "word" and self.text.upper() == kw


def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise _syntax(f"cannot parse near {text[pos : pos + 20]!r}")
        pos = m.end()
        if m.group("bad"):
            raise _syntax("unbalanced quotes" if m.group("bad") == '"' else f"unexpected {m.group('bad')!r}")
        for kind in ("quoted", "paren", "op", "word"):
            if m.group(kind) is not None:
                toks.append(Tok(kind, m.group(kind)))
                break
    return toks


class _Cursor:
    def __init__(self, toks: Sequence[Tok]) -> None:
        self.toks = list(toks)
        self.i = 0

    def peek(self, k: int = 0) -> Tok | None:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def next(self) -> Tok:
        tok = self.peek()
        if tok is None:
            raise _syntax("unexpected end of expression")
        self.i += 1
        return tok

    def done(self) -> bool:
        return self.i >= len(self.toks)


# --------------------------------------------------------------------------- value helpers


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _str(v: Any) -> str:
    if isinstance(v, datetime):
        return _iso(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _compare(left: Any, op: str, right: Any, *, case_insensitive: bool, wildcards: bool) -> bool:
    if left is None or right is None:
        return False
    ln, rn = _num(left), _num(right)
    if op in ("=", "==", "!="):
        if ln is not None and rn is not None:
            eq = ln == rn
        else:
            ls, rs = _str(left), _str(right)
            if case_insensitive:
                ls, rs = ls.lower(), rs.lower()
            if wildcards and "*" in rs:
                pattern = "^" + ".*".join(re.escape(p) for p in rs.split("*")) + "$"
                eq = re.match(pattern, ls, re.DOTALL) is not None
            else:
                eq = ls == rs
        return eq if op != "!=" else not eq
    if ln is not None and rn is not None:
        a: Any = ln
        b: Any = rn
    else:
        a, b = _str(left), _str(right)
    if op == "<":
        return bool(a < b)
    if op == ">":
        return bool(a > b)
    if op == "<=":
        return bool(a <= b)
    if op == ">=":
        return bool(a >= b)
    raise _syntax(f"unknown operator {op!r}")  # pragma: no cover


# --------------------------------------------------------------------------- search-command expressions

Pred = Callable[[Event], bool]


def _and(a: Pred, b: Pred) -> Pred:
    return lambda e: a(e) and b(e)


def _or(a: Pred, b: Pred) -> Pred:
    return lambda e: a(e) or b(e)


def _not(a: Pred) -> Pred:
    return lambda e: not a(e)


def _field_cmp(fld: str, op: str, val: str) -> Pred:
    def pred(e: Event) -> bool:
        v = e.get(fld)
        if op == "!=":
            return v is not None and not _compare(v, "=", val, case_insensitive=True, wildcards=True)
        return _compare(v, op, val, case_insensitive=True, wildcards=True)

    return pred


def _free_text(term: str) -> Pred:
    needle = term.lower()
    if "*" in needle:
        pattern = ".*".join(re.escape(p) for p in needle.split("*"))
        rx = re.compile(pattern, re.DOTALL)
        return lambda e: rx.search(str(e.get("_raw", "")).lower()) is not None
    return lambda e: needle in str(e.get("_raw", "")).lower()


@dataclass
class SearchExpr:
    pred: Pred
    fields: frozenset[str]
    """Field names referenced by comparisons (used to decide whether ``index`` was specified)."""


def parse_search_terms(text: str) -> SearchExpr:
    """Boolean search-term expression: implicit AND, OR, NOT, parentheses, ``field op value``, free text."""
    cur = _Cursor(tokenize(text))
    referenced: set[str] = set()

    def or_expr() -> Pred:
        left = and_expr()
        while (t := cur.peek()) is not None and t.is_kw("OR"):
            cur.next()
            left = _or(left, and_expr())
        return left

    def and_expr() -> Pred:
        left = not_expr()
        while (
            (t := cur.peek()) is not None and not t.is_kw("OR") and not (t.kind == "paren" and t.text == ")")
        ):
            if t.is_kw("AND"):
                cur.next()
            left = _and(left, not_expr())
        return left

    def not_expr() -> Pred:
        t = cur.peek()
        if t is not None and t.is_kw("NOT"):
            cur.next()
            return _not(not_expr())
        return primary()

    def primary() -> Pred:
        t = cur.next()
        if t.kind == "paren" and t.text == "(":
            inner = or_expr()
            close = cur.next()
            if close.text != ")":
                raise _syntax("missing closing parenthesis")
            return inner
        if t.kind == "paren":
            raise _syntax(f"unexpected {t.text!r}")
        if t.kind == "op":
            raise _syntax(f"comparison {t.text!r} has no field name")
        if t.is_kw("AND") or t.is_kw("OR"):
            raise _syntax(f"{t.text} has no left operand")
        nxt = cur.peek()
        if t.kind == "word" and nxt is not None and nxt.kind == "op":
            cur.next()
            val = cur.peek()
            if val is None or val.kind in ("op", "paren"):
                raise _syntax(f"comparison '{t.text}{nxt.text}' has no value")
            cur.next()
            referenced.add(t.text)
            if t.text.lower() in ("earliest", "latest"):
                raise _unsupported("time modifiers inside the search string (pass earliest/latest instead)")
            return _field_cmp(t.text, nxt.text, val.value)
        if t.kind == "word" and nxt is not None and nxt.is_kw("IN"):
            raise _unsupported("the IN operator")
        if t.kind == "word" and t.text.startswith("`"):
            raise _unsupported("macros")
        return _free_text(t.value)

    if cur.done():
        return SearchExpr(pred=lambda e: True, fields=frozenset())
    pred = or_expr()
    if not cur.done():
        raise _syntax(f"unexpected {cur.next().text!r}")
    return SearchExpr(pred=pred, fields=frozenset(referenced))


# --------------------------------------------------------------------------- where expressions

Val = Callable[[Row], Any]


def parse_where(text: str) -> Pred:
    """``where`` expression: comparisons between fields, numbers and "strings"; AND/OR/NOT; isnull/isnotnull."""
    cur = _Cursor(tokenize(text))
    if cur.done():
        raise _syntax("where command requires an expression")

    def or_expr() -> Pred:
        left = and_expr()
        while (t := cur.peek()) is not None and t.is_kw("OR"):
            cur.next()
            left = _or(left, and_expr())
        return left

    def and_expr() -> Pred:
        left = not_expr()
        while (t := cur.peek()) is not None and t.is_kw("AND"):
            cur.next()
            left = _and(left, not_expr())
        return left

    def not_expr() -> Pred:
        t = cur.peek()
        if t is not None and t.is_kw("NOT"):
            cur.next()
            return _not(not_expr())
        return comparison()

    def operand() -> Val:
        t = cur.next()
        if t.kind == "quoted":
            s = t.value
            return lambda r: s
        if t.kind == "word":
            if _num(t.text) is not None:
                n = float(t.text)
                return lambda r: n
            name = t.text
            return lambda r: r.get(name)
        raise _syntax(f"expected a value, got {t.text!r}")

    def comparison() -> Pred:
        t = cur.peek()
        if t is not None and t.kind == "paren" and t.text == "(":
            cur.next()
            inner = or_expr()
            if cur.next().text != ")":
                raise _syntax("missing closing parenthesis")
            return inner
        nxt = cur.peek(1)
        if t is not None and t.kind == "word" and nxt is not None and nxt.text == "(":
            func = t.text.lower()
            if func not in ("isnull", "isnotnull"):
                raise _unsupported(f"where function {t.text}()")
            cur.next()
            cur.next()
            arg = cur.next()
            if arg.kind != "word" or cur.next().text != ")":
                raise _syntax(f"{func}() takes one field name")
            name = arg.text
            if func == "isnull":
                return lambda r: r.get(name) is None
            return lambda r: r.get(name) is not None
        left = operand()
        op_tok = cur.peek()
        if op_tok is None or op_tok.kind != "op":
            raise _syntax("where expects a comparison such as 'count > 3'")
        cur.next()
        rhs = cur.peek()
        if rhs is None or rhs.kind in ("op", "paren"):
            raise _syntax(f"comparison operator {op_tok.text!r} has no right operand")
        right = operand()
        op = op_tok.text
        return lambda r: _compare(left(r), op, right(r), case_insensitive=False, wildcards=False)

    pred = or_expr()
    if not cur.done():
        raise _syntax(f"unexpected {cur.next().text!r} in where")
    return pred


# --------------------------------------------------------------------------- stats

# Real Splunk stats functions. Ones not implemented here are "unsupported"; anything else is a search error.
_SPLUNK_STATS_FUNCS = frozenset(
    {
        "avg", "count", "dc", "distinct_count", "estdc", "estdc_error", "exactperc", "max", "mean", "median",
        "min", "mode", "perc", "percentile", "range", "stdev", "stdevp", "sum", "sumsq", "upperperc", "var",
        "varp", "first", "last", "list", "values", "earliest", "earliest_time", "latest", "latest_time",
        "per_day", "per_hour", "per_minute", "per_second", "rate", "rate_avg", "rate_sum",
    }
)  # fmt: skip
_IMPLEMENTED = frozenset({"count", "dc", "distinct_count", "sum", "avg", "mean", "min", "max", "values"})
_AGG_RE = re.compile(
    r"^(?P<func>[A-Za-z_]\w*)(?:\((?P<arg>[^()]*)\))?(?:\s+as\s+(?P<alias>[A-Za-z_][\w.]*))?$", re.IGNORECASE
)
_IDENT = re.compile(r"^[A-Za-z_][\w.]*$")


@dataclass(frozen=True)
class Agg:
    func: str
    arg: str | None
    alias: str


def _split_commas(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    buf = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return parts


def parse_stats(text: str) -> tuple[list[Agg], list[str]]:
    by_split = re.split(r"\s+by\s+", " " + text.strip() + " ", maxsplit=1, flags=re.IGNORECASE)
    agg_text = by_split[0].strip()
    if not agg_text:
        raise _syntax("stats requires at least one aggregation")
    if re.search(r"\b\w+=\S", agg_text):
        raise _unsupported("stats options")
    # Aggregations are separated by commas or spaces (`count dc(user)`), with optional `as alias`.
    items: list[str] = []
    for chunk in _split_commas(agg_text):
        words = re.findall(r"[^\s(]+(?:\([^)]*\))?", chunk)
        j = 0
        while j < len(words):
            item = words[j]
            if j + 2 < len(words) and words[j + 1].lower() == "as":
                item = f"{item} as {words[j + 2]}"
                j += 2
            items.append(item)
            j += 1
    aggs: list[Agg] = []
    for item in items:
        m = _AGG_RE.match(item.strip())
        if not m:
            raise _syntax(f"cannot parse stats aggregation {item.strip()!r}")
        func = m.group("func").lower()
        base = re.sub(r"\d+$", "", func)
        if func not in _SPLUNK_STATS_FUNCS and base not in ("p", "perc", "exactperc", "upperperc"):
            raise _syntax(f"Unknown stats function '{m.group('func')}'")
        if func not in _IMPLEMENTED:
            raise _unsupported(f"stats function {func}()")
        arg = m.group("arg")
        if arg is not None:
            arg = arg.strip()
            if not _IDENT.match(arg):
                raise _unsupported(f"stats argument {arg!r}")
        elif func != "count":
            raise _syntax(f"stats function {func} requires a field argument")
        alias = m.group("alias") or (f"{func}({arg})" if arg is not None else func)
        aggs.append(Agg(func=func, arg=arg, alias=alias))
    by: list[str] = []
    if len(by_split) == 2:
        by = [b for b in re.split(r"[,\s]+", by_split[1].strip()) if b]
        if not by:
            raise _syntax("stats 'by' clause has no fields")
        for b in by:
            if not _IDENT.match(b):
                raise _syntax(f"invalid field name in by clause: {b!r}")
    return aggs, by


def _aggregate(agg: Agg, rows: Sequence[Row]) -> Any:
    if agg.func == "count":
        if agg.arg is None:
            return len(rows)
        return sum(1 for r in rows if r.get(agg.arg) is not None)
    assert agg.arg is not None
    values = [r[agg.arg] for r in rows if r.get(agg.arg) is not None]
    if agg.func in ("dc", "distinct_count"):
        return len({_str(v) for v in values})
    if agg.func == "values":
        return sorted({_str(v) for v in values})
    nums = [n for n in (_num(v) for v in values) if n is not None]
    if agg.func in ("min", "max"):
        if nums and len(nums) == len(values):
            n = min(nums) if agg.func == "min" else max(nums)
            return int(n) if n.is_integer() else n
        if not values:
            return None
        strs = [_str(v) for v in values]
        return min(strs) if agg.func == "min" else max(strs)
    if not nums:
        return None
    if agg.func == "sum":
        s = float(sum(nums))
        return int(s) if s.is_integer() else s
    return sum(nums) / len(nums)  # avg / mean


def run_stats(rows: Sequence[Row], aggs: Sequence[Agg], by: Sequence[str]) -> list[Row]:
    if not by:
        return [{a.alias: _aggregate(a, rows) for a in aggs}]
    groups: dict[tuple[str, ...], list[Row]] = {}
    for r in rows:
        key_vals = [r.get(b) for b in by]
        if any(v is None for v in key_vals):
            continue
        groups.setdefault(tuple(_str(v) for v in key_vals), []).append(r)
    out: list[Row] = []
    for key in sorted(groups):
        row: Row = dict(zip(by, key, strict=True))
        for a in aggs:
            row[a.alias] = _aggregate(a, groups[key])
        out.append(row)
    return out


# --------------------------------------------------------------------------- other commands


def _field_list(text: str) -> list[str]:
    names = [f for f in re.split(r"[,\s]+", text.strip()) if f]
    for f in names:
        if not re.fullmatch(r"[A-Za-z_*][\w.*]*", f):
            raise _syntax(f"invalid field name {f!r}")
    return names


def _match_field(pattern: str, name: str) -> bool:
    if "*" not in pattern:
        return pattern == name
    return re.fullmatch(".*".join(re.escape(p) for p in pattern.split("*")), name) is not None


def _sort_key(v: Any) -> tuple[int, float, str]:
    n = _num(v)
    if v is None:
        return (2, 0.0, "")
    if n is not None:
        return (0, n, "")
    return (1, 0.0, _str(v))


def _row_sort_key(name: str) -> Callable[[Row], tuple[int, float, str]]:
    return lambda r: _sort_key(r.get(name))


SUPPORTED_COMMANDS = ("search", "where", "stats", "table", "fields", "head", "sort", "dedup", "rename")


def _apply_command(cmd: str, rest: str, rows: list[Row]) -> list[Row]:
    if cmd == "search":
        expr = parse_search_terms(rest)
        return [r for r in rows if expr.pred(r)]
    if cmd == "where":
        pred = parse_where(rest)
        return [r for r in rows if pred(r)]
    if cmd == "stats":
        aggs, by = parse_stats(rest)
        return run_stats(rows, aggs, by)
    if cmd == "table":
        names = _field_list(rest)
        if not names:
            raise _syntax("table requires field names")
        return [{k: v for k, v in r.items() if any(_match_field(n, k) for n in names)} for r in rows]
    if cmd == "fields":
        text = rest.strip()
        remove = text.startswith("-")
        names = _field_list(text.lstrip("+-"))
        if not names:
            raise _syntax("fields requires field names")
        keep_internal = not remove
        out = []
        for r in rows:
            if remove:
                out.append({k: v for k, v in r.items() if not any(_match_field(n, k) for n in names)})
            else:
                out.append(
                    {
                        k: v
                        for k, v in r.items()
                        if any(_match_field(n, k) for n in names)
                        or (keep_internal and k in ("_time", "_raw"))
                    }
                )
        return out
    if cmd == "head":
        text = rest.strip()
        m = re.fullmatch(r"(?:limit=)?(\d+)", text) if text else None
        if text and not m:
            raise _unsupported(f"head {text!r}")
        return rows[: int(m.group(1)) if m else 10]
    if cmd == "sort":
        text = rest.strip()
        limit: int | None = None
        lm = re.match(r"^(\d+)\s+", text)
        if lm:
            limit = int(lm.group(1))
            text = text[lm.end() :]
        specs = [s for s in re.split(r"[,\s]+", text) if s]
        if not specs:
            raise _syntax("sort requires field names")
        out = list(rows)
        for spec in reversed(specs):
            desc = spec.startswith("-")
            name = spec.lstrip("+-")
            if not _IDENT.match(name):
                raise _unsupported(f"sort clause {spec!r}")
            out.sort(key=_row_sort_key(name), reverse=desc)
        return out[:limit] if limit is not None else out
    if cmd == "dedup":
        names = _field_list(rest)
        if not names or any("*" in n for n in names):
            raise _syntax("dedup requires field names")
        seen: set[tuple[str, ...]] = set()
        out = []
        for r in rows:
            vals = [r.get(n) for n in names]
            if any(v is None for v in vals):
                continue
            key = tuple(_str(v) for v in vals)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out
    if cmd == "rename":
        pairs = re.findall(r"([\w.]+)\s+as\s+([\w.]+)", rest, re.IGNORECASE)
        if not pairs or re.sub(r"([\w.]+)\s+as\s+([\w.]+)|[,\s]", "", rest, flags=re.IGNORECASE):
            raise _syntax("rename expects 'field AS newname'")
        out = []
        for r in rows:
            nr = dict(r)
            for src, dst in pairs:
                if src in nr:
                    nr[dst] = nr.pop(src)
            out.append(nr)
        return out
    raise _unsupported(f"command '{cmd}'")


def _row_out(row: Row) -> Row:
    return {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in row.items()}


# --------------------------------------------------------------------------- engine


class SimEngine:
    """Answers the six gateway ops for one scenario at a fixed ``now``."""

    def __init__(self, scenario: Scenario, now: datetime | None = None) -> None:
        if now is not None and now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        self.scenario = scenario
        self.now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        self.events: dict[str, list[Event]] = {}
        for idx in scenario.indexes:
            evs: list[Event] = []
            for st in idx.sourcetypes:
                evs.extend(generate_events(scenario.seed, idx.name, st, self.now))
            evs.sort(key=lambda e: e["_time"], reverse=True)
            self.events[idx.name] = evs

    # ---- helpers

    def _window(self, earliest: str, latest: str = "now") -> tuple[datetime | None, datetime | None]:
        lo = parse_time(earliest, self.now)
        hi = parse_time(latest, self.now) if latest.strip() not in ("", "0") else None
        if lo is not None and hi is not None and lo > hi:
            raise SimError("invalid_argument", "earliest must not be after latest")
        return lo, hi

    @staticmethod
    def _in(events: Iterable[Event], lo: datetime | None, hi: datetime | None) -> list[Event]:
        return [e for e in events if (lo is None or e["_time"] >= lo) and (hi is None or e["_time"] < hi)]

    # ---- ops

    def list_saved_searches(self) -> list[SavedSearch]:
        return list(self.scenario.saved_searches)

    def describe_index(self, name: str) -> IndexInfo:
        if name not in self.events:
            return IndexInfo(name=name, exists=False)
        evs = self.events[name]
        return IndexInfo(
            name=name,
            exists=True,
            total_event_count=len(evs),
            earliest_event=evs[-1]["_time"] if evs else None,
            latest_event=evs[0]["_time"] if evs else None,
        )

    def sourcetype_stats(self, index: str, earliest: str) -> list[SourcetypeStats]:
        """Counts are within the window; ``latest_event`` is the newest event ever seen (so a stopped feed shows its age).

        Sourcetypes with events only outside the window are listed with ``event_count=0``.
        """
        lo, hi = self._window(earliest)
        by_st: dict[str, list[Event]] = {}
        for e in self.events.get(index, []):
            by_st.setdefault(e["sourcetype"], []).append(e)
        return [
            SourcetypeStats(
                index=index,
                sourcetype=st,
                event_count=len(self._in(evs, lo, hi)),
                latest_event=evs[0]["_time"],
                window_earliest=earliest,
            )
            for st, evs in sorted(by_st.items())
        ]

    def field_summary(self, index: str, sourcetype: str | None, earliest: str) -> FieldSummary:
        lo, hi = self._window(earliest)
        evs = [
            e
            for e in self._in(self.events.get(index, []), lo, hi)
            if sourcetype is None or e["sourcetype"] == sourcetype
        ]
        counts: dict[str, int] = {}
        distinct: dict[str, set[str]] = {}
        for e in evs:
            for k, v in e.items():
                if k.startswith("_") or v is None:
                    continue
                counts[k] = counts.get(k, 0) + 1
                distinct.setdefault(k, set()).add(_str(v))
        return FieldSummary(
            index=index,
            sourcetype=sourcetype,
            window_earliest=earliest,
            event_count=len(evs),
            fields=tuple(
                FieldStat(name=k, count=counts[k], distinct_count=len(distinct[k])) for k in sorted(counts)
            ),
        )

    def run_search(self, spl: str, earliest: str, latest: str = "now", max_rows: int = 100) -> SearchResult:
        if max_rows < 1:
            raise SimError("invalid_argument", "max_rows must be >= 1")
        try:
            lo, hi = self._window(earliest, latest)
        except SimError as exc:
            if exc.kind == "invalid_argument":
                raise SimError("search_error", exc.message) from None
            raise
        text = spl.strip()
        if not text:
            raise _syntax("empty search")
        if "`" in text:
            raise _unsupported("macros")
        segments, has_sub = split_pipeline(text)
        if has_sub:
            raise _unsupported("subsearches")
        base, commands = segments[0], segments[1:]
        if not base and commands:
            first = commands[0].split(None, 1)[0].lower() if commands[0] else ""
            if not first:
                raise _syntax("empty command after '|'")
            raise _unsupported(f"generating command '{first}'")
        if base.lower().startswith("search "):
            base = base[7:]
        expr = parse_search_terms(base)
        candidates: list[Event] = []
        for name, evs in self.events.items():
            if "index" not in expr.fields and name != DEFAULT_INDEX:
                continue
            candidates.extend(self._in(evs, lo, hi))
        candidates.sort(key=lambda e: e["_time"], reverse=True)
        rows: list[Row] = [e for e in candidates if expr.pred(e)]
        scan_count = len(rows)
        for seg in commands:
            if not seg.strip():
                raise _syntax("empty command after '|'")
            parts = seg.split(None, 1)
            rows = _apply_command(parts[0].lower(), parts[1] if len(parts) > 1 else "", rows)
        out = [_row_out(r) for r in rows]
        return SearchResult(
            spl=spl,
            earliest=earliest,
            latest=latest,
            rows=tuple(out[:max_rows]),
            truncated=len(out) > max_rows,
            scan_count=scan_count,
        )

    def scheduler_history(self, rule_name: str, earliest: str) -> list[SchedulerRun]:
        lo, _ = self._window(earliest)
        runs: list[SchedulerRun] = []
        for spec in self.scenario.scheduler:
            if spec.rule_name != rule_name:
                continue
            start = self.now - parse_duration(spec.offset)
            every = parse_duration(spec.every)
            for k in range(spec.count):
                t = start - every * k
                if lo is not None and t < lo:
                    break
                runs.append(
                    SchedulerRun(
                        rule_name=rule_name,
                        scheduled_time=t,
                        status=spec.status,
                        result_count=spec.result_count,
                        message=spec.message,
                    )
                )
        runs.sort(key=lambda r: r.scheduled_time, reverse=True)
        return runs
