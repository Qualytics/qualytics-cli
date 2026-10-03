"""Name the unnamed expressions in a query's outer SELECT list.

``containers import`` gives every computed-table column a name so the
satisfiesExpression check built from the profiled fields can reference it.
Only the outer SELECT list is rewritten, and only by inserting ``as expr_N``
after an expression that has no alias; every other character of the query is
kept. When the query can't be read with confidence it is returned unchanged,
which is what the UI would send.
"""

import re
from collections.abc import Iterator
from typing import NamedTuple

_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W\d][\w$]*")
_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_DOLLAR_TAG = re.compile(r"\$(?:[^\W\d]\w*)?\$")

_PAIRS = {"(": ")", "{": "}", "[": "]"}
# `array<`, `map<` and `struct<` open a type whose commas don't split columns.
_TYPE_WORDS = frozenset({"array", "map", "struct"})
# Words that end an expression themselves (literals, the END of a CASE). After
# a complete expression they are an alias without AS instead: `max(d) end`.
_VALUE_WORDS = frozenset({"end", "false", "null", "true"})
# After `INTERVAL '1'` one of these is the literal's unit, not an alias.
_INTERVAL_UNITS = frozenset(
    "year years quarter quarters month months week weeks day days hour hours "
    "minute minutes second seconds millisecond milliseconds microsecond "
    "microseconds".split()
)
# Words after which the next token is an operand, never an alias.
_OPERATOR_WORDS = frozenset(
    {
        "and",
        "as",
        "between",
        "case",
        "collate",
        "distinct",
        "else",
        "escape",
        "exists",
        "for",
        "from",
        "ilike",
        "in",
        "is",
        "like",
        "not",
        "or",
        "over",
        "then",
        "to",
        "when",
    }
)
# Reaching one of these before the outer FROM means the SELECT list is not a
# plain one (set operation, SELECT INTO, ...), so the query is left alone.
_STOP_WORDS = frozenset({"except", "intersect", "into", "minus", "select", "union"})
# Characters besides letters and digits that would join onto an inserted alias.
_GLUED = frozenset({"_", "$", "'", '"', "`", "["})


class _Token(NamedTuple):
    kind: str  # word, number, string, quoted (identifier) or punct
    text: str
    start: int
    end: int
    depth: int  # bracket depth; an opening or closing bracket gets the outer one


class _Unreadable(Exception):
    """The query can't be tokenized unambiguously."""


def add_missing_aliases(sql: str) -> tuple[str, int]:
    """Give unnamed expressions in the outer SELECT list ``expr_N`` aliases.

    ``*``, column references and expressions that already have an alias are
    left alone, except that a column reference whose name another column
    already has gets an alias too. Returns the query and the number of aliases
    added; the query comes back unchanged when it can't be read with confidence.
    """
    try:
        items = _outer_select_items(sql)
    except _Unreadable:
        return sql, 0
    if items is None:
        return sql, 0

    taken = {
        token.text.strip('"`[]').lower()
        for item in items
        for token in item
        if token.kind in ("word", "quoted")
    }
    repeated = _repeated_column_refs(items)
    pieces: list[str] = []
    position = number = added = 0
    for index, item in enumerate(items):
        if not (_needs_alias(item) or index in repeated):
            continue
        number += 1
        while f"expr_{number}" in taken:
            number += 1
        end = item[-1].end
        # Keep the alias from running into what follows, e.g. `count(*)from`.
        following = sql[end : end + 1]
        spacer = " " if following.isalnum() or following in _GLUED else ""
        pieces += [sql[position:end], f" as expr_{number}{spacer}"]
        position = end
        added += 1

    if not added:
        return sql, 0
    pieces.append(sql[position:])
    return "".join(pieces), added


def _outer_select_items(sql: str) -> list[list[_Token]] | None:
    """Split the outer query's SELECT list into items, or return None if unsure.

    The outer SELECT is the first one outside any brackets, which skips the
    SELECTs of WITH clauses and subqueries. Its list ends at the first FROM at
    the same level that isn't part of ``IS [NOT] DISTINCT FROM``.
    """
    tokens = _tokens(sql)
    for token in tokens:
        if token.depth == 0 and _word(token) == "select":
            break
    else:
        return None

    items: list[list[_Token]] = [[]]
    for token in tokens:
        if token.depth == 0:
            if token.text == ",":
                items.append([])
                continue
            word = _word(token)
            if word == "from" and not _is_distinct_from(items[-1]):
                break
            if word in _STOP_WORDS or token.text == ";":
                return None
        items[-1].append(token)
    else:
        return None

    # Read the rest too: a malformed tail, or quoting the tokenizer doesn't know
    # that knocked it out of step, ends in an unterminated token.
    for _ in tokens:
        pass
    items[0] = _without_modifiers(items[0])
    return items


def _needs_alias(item: list[_Token]) -> bool:
    """Return True when a SELECT list item is an expression without an alias."""
    if not item:
        return False
    outer = [token for token in item if token.depth == 0]
    for i, token in enumerate(outer):
        if _word(token) == "as":
            return False  # `expr AS name`, `expr AS (a, b)`
        if token.text == "*" and (i == 0 or outer[i - 1].text == "."):
            return False  # `*`, `t.*`, `* EXCLUDE (...)`
    if _is_column_ref(item):
        return False  # a column reference keeps its own name
    if (
        len(item) > 1
        and _may_be_alias(item)
        and _ends_expression(item[-2])
        and not _ends_with_operand(item)
    ):
        return False  # `expr name`, an alias without AS
    return True


def _repeated_column_refs(items: list[list[_Token]]) -> set[int]:
    """Return the indexes of column references whose name is already in use.

    `a.id, b.id` would give two `id` columns, so the second one needs an alias.
    Names the query's own aliases give are never changed, so a column
    reference that shares one gets the alias instead.
    """
    used = {
        _output_name(item)
        for item in items
        if not _is_column_ref(item) and not _needs_alias(item)
    } - {None}
    repeated = set()
    for i, item in enumerate(items):
        if _is_column_ref(item):
            name = _output_name(item)
            if name in used:
                repeated.add(i)
            used.add(name)
    return repeated


def _output_name(item: list[_Token]) -> str | None:
    """Return the name an item's column keeps, or None if unknown.

    Unquoted names fold to lowercase. Quoted names keep their case: `"ID"` and
    `"id"` are different columns, and the dataplane reads them case-sensitively.
    """
    if not item or item[-1].kind not in ("word", "quoted"):
        return None
    last = item[-1]
    return last.text[1:-1] if last.kind == "quoted" else last.text.lower()


def _is_column_ref(item: list[_Token]) -> bool:
    """Return True for a plain column reference such as `id` or `t."Col"`."""
    return len(item) % 2 == 1 and all(
        _is_name(token) if i % 2 == 0 else token.text == "."
        for i, token in enumerate(item)
    )


def _without_modifiers(item: list[_Token]) -> list[_Token]:
    """Drop ALL, DISTINCT [ON (...)] and TOP n [PERCENT] [WITH TIES]."""
    i = 0
    while i < len(item):
        word = _word(item[i])
        if word in ("all", "distinct"):
            i += 1
            if i + 1 < len(item) and _word(item[i]) == "on" and item[i + 1].text == "(":
                i = _past_group(item, i + 1)
        elif word == "top":
            i += 1
            if i < len(item) and item[i].text == "(":
                i = _past_group(item, i)
            elif i < len(item) and item[i].kind == "number":
                i += 1
            if i < len(item) and _word(item[i]) == "percent":
                i += 1
            if [_word(token) for token in item[i : i + 2]] == ["with", "ties"]:
                i += 2
        else:
            break
    return item[i:]


def _past_group(item: list[_Token], i: int) -> int:
    """Return the index just past the bracketed group that opens at ``item[i]``."""
    for k in range(i + 1, len(item)):
        if item[k].depth == item[i].depth:
            return k + 1
    return len(item)


def _is_distinct_from(item: list[_Token]) -> bool:
    """Return True when a FROM after ``item`` belongs to IS [NOT] DISTINCT FROM."""
    words = [_word(token) for token in item[-3:]]
    return words[-2:] == ["is", "distinct"] or words == ["is", "not", "distinct"]


def _may_be_alias(item: list[_Token]) -> bool:
    """Return True when the item's last token could be an alias without AS."""
    word = _word(item[-1])
    if word == "end":
        # END closes a CASE unless the item has more ENDs than CASEs
        words = [_word(token) for token in item if token.depth == 0]
        return words.count("end") > words.count("case")
    return _is_name(item[-1]) or word in _VALUE_WORDS


def _ends_with_operand(item: list[_Token]) -> bool:
    """Return True when the item's last word is an operand, not an alias.

    `INTERVAL '1' DAY` ends in the literal's unit, and `ts AT TIME ZONE tz` in
    the zone it converts to.
    """
    words = [_word(token) for token in item[-4:]]
    if len(item) > 2 and words[-3] == "interval":
        return item[-2].kind in ("number", "string") and words[-1] in _INTERVAL_UNITS
    return len(item) > 4 and words[:3] == ["at", "time", "zone"]


def _is_name(token: _Token) -> bool:
    """Return True for a token that could be a column name or an alias."""
    if token.kind == "quoted":
        return True
    word = _word(token)
    return bool(word) and word not in _VALUE_WORDS and word not in _OPERATOR_WORDS


def _ends_expression(token: _Token) -> bool:
    """Return True when ``token`` can be the last token of an expression."""
    if token.kind in ("number", "string", "quoted"):
        return True
    if token.kind == "word":
        return _word(token) not in _OPERATOR_WORDS
    return token.text in (")", "}", "]")


def _word(token: _Token) -> str:
    return token.text.lower() if token.kind == "word" else ""


def _tokens(sql: str) -> Iterator[_Token]:
    """Yield the tokens of ``sql`` with their bracket depth.

    Whitespace and comments are skipped. Raises _Unreadable for an
    unterminated string or comment and for unbalanced brackets.
    """
    stack: list[str] = []  # closing brackets still expected
    earlier: _Token | None = None
    previous: _Token | None = None
    i = 0
    while i < len(sql):
        if space := _SPACE.match(sql, i):
            i = space.end()
            continue
        if sql.startswith("--", i):
            newline = sql.find("\n", i)
            i = len(sql) if newline == -1 else newline + 1
            continue
        if sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            if close == -1:
                raise _Unreadable
            i = close + 2
            continue

        char = sql[i]
        # `a[1]`, `v['key']`, `ARRAY[1, 2]`: a bracket right after an expression
        # or ARRAY is a subscript. Anywhere else `[My Col]` is a quoted name.
        subscript = (
            char == "["
            and previous is not None
            and (
                _word(previous) == "array"
                or (previous.end == i and _ends_expression(previous))
            )
        )
        if char in "'\"`" or (char == "[" and not subscript):
            end = _quoted_end(sql, i, "]" if char == "[" else char)
            kind = "string" if char == "'" else "quoted"
        elif tag := _DOLLAR_TAG.match(sql, i):
            close = sql.find(tag.group(), tag.end())
            if close == -1:
                raise _Unreadable
            end, kind = close + len(tag.group()), "string"
        elif word := _WORD.match(sql, i):
            end, kind = word.end(), "word"
        elif number := _NUMBER.match(sql, i):
            end, kind = number.end(), "number"
        else:
            end, kind = i + 1, "punct"

        text = sql[i:end]
        if kind == "punct" and stack and text == stack[-1]:
            stack.pop()
        elif kind == "punct" and text in (")", "}", "]"):
            raise _Unreadable
        token = _Token(kind, text, i, end, len(stack))
        yield token

        if kind == "punct" and text in _PAIRS:
            stack.append(_PAIRS[text])
        elif (
            text == "<"
            and previous is not None
            and _word(previous) in _TYPE_WORDS
            # a type follows `::`, a struct field's `:`, or an enclosing type;
            # elsewhere `map < 3` compares a column
            and (stack[-1:] == [">"] or (earlier is not None and earlier.text == ":"))
        ):
            stack.append(">")
        earlier, previous = previous, token
        i = end
    if stack:
        raise _Unreadable


def _quoted_end(sql: str, start: int, close: str) -> int:
    """Return the index just past the quoted token that opens at ``start``.

    A doubled closing character is an escaped one. A closing quote after an
    odd run of backslashes ends the token in some dialects but is escaped in
    others, so it makes the query unreadable.
    """
    i = start + 1
    while (j := sql.find(close, i)) != -1:
        if close in "'\"":
            segment = sql[i:j]
            if (len(segment) - len(segment.rstrip("\\"))) % 2:
                raise _Unreadable
        if not sql.startswith(close, j + 1):
            return j + 1
        i = j + 2
    raise _Unreadable
