"""REST survey responses -> the survey-analyst TSV (SKILL.md step 2, read by analyze.py load_tsv).

Header: `responseId`, `submitted`, then `[TYPE] question` per question in questionnaire
order; row-based types get one `[TYPE] question :: row` column per row (MATRIX_TEXT one
`[TEXT] question :: row :: column` per row and column). One line per response; empty
cell = no answer; MULTI labels joined with ` | `, an "Other" text as `Other: <text>`; tabs
and line breaks inside any cell become spaces. Respondent email, `parameters` and
EMAIL-type questions never reach the file.
"""
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from .output import atomic_writer

# REST question type -> TSV header type; None = dropped. Types not listed are written as
# TEXT with a readable value and reported as unmapped. Types in ROW_TYPES get one column
# per row (see _rows).
TYPE_MAP: Dict[str, Optional[str]] = {
    "NPS": "NPS",
    "RATING": "RATING",
    "NUMBER": "NUMBER",
    "SINGLE_CHOICE": "CHOICE",
    "IMAGE_SINGLE_CHOICE": "CHOICE",
    "MULTIPLE_CHOICE": "MULTI",
    "IMAGE_MULTIPLE_CHOICE": "MULTI",
    "MATRIX_SINGLE_CHOICE": "MATRIX",
    "TEXT": "TEXT",
    "DATE": "TEXT",
    "PLACE": "TEXT",
    "EMOJI": "RATING",
    "SORTING": "MATRIX",
    "SEMANTIC_DIFFERENTIAL": "MATRIX",
    "DIVIDE_POINTS": "MATRIX",
    "MATRIX_MULTIPLE_CHOICE": "MULTI",
    "MATRIX_TEXT": "TEXT",
    "EMAIL": None,
}

ROW_TYPES = {"MATRIX_SINGLE_CHOICE", "SORTING", "SEMANTIC_DIFFERENTIAL", "DIVIDE_POINTS",
             "MATRIX_MULTIPLE_CHOICE", "MATRIX_TEXT"}

MULTI_SEP = " | "
ROW_SEP = " :: "
PAIR_SEP = " \u2013 "  # SEMANTIC_DIFFERENTIAL row: "<left> – <right>"


class Column(NamedTuple):
    type: str
    question: str
    row: Optional[str]
    qid: Any

    def header(self) -> str:
        if self.row is not None:
            return "[%s] %s%s%s" % (self.type, self.question, ROW_SEP, self.row)
        return "[%s] %s" % (self.type, self.question)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _qid_key(qid: Any) -> Tuple[int, Any]:
    if isinstance(qid, int) and not isinstance(qid, bool):
        return (0, qid)
    try:
        return (0, int(str(qid)))
    except ValueError:
        return (1, str(qid))


def _question(answer: Any) -> Optional[dict]:
    q = answer.get("question") if isinstance(answer, dict) else None
    return q if isinstance(q, dict) else None


def _rest_type(q: dict) -> str:
    return str(q.get("type") or "UNKNOWN")


def _objects(answer: Any) -> List[Any]:
    """The answer as a list of items (an object, a list of objects, or a scalar)."""
    if answer is None:
        return []
    return list(answer) if isinstance(answer, list) else [answer]


def _item_labels(item: dict) -> List[str]:
    labels = item.get("labels")
    labels = labels if isinstance(labels, list) else [labels]
    return [str(x) for x in labels if x not in (None, "")]


def _labels(answer: Any) -> List[str]:
    out = []
    for item in _objects(answer):
        if isinstance(item, dict):
            out += _item_labels(item)
        elif item not in (None, ""):
            out.append(str(item))
    return out


def _first(value: Any) -> Any:
    """A matrix/choice `value`: a scalar or a one-element list."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _value(answer: Any) -> Any:
    """The free value of an answer: a scalar as is, or the first object's `value`."""
    for item in _objects(answer):
        v = _first(item.get("value")) if isinstance(item, dict) else item
        if v not in (None, ""):
            return v
    return None


def _other(answer: Any) -> Optional[str]:
    """The "Other" text of a choice answer: the `value` of its object, if any."""
    for item in _objects(answer):
        if isinstance(item, dict):
            v = _first(item.get("value"))
            if v not in (None, ""):
                return "Other: %s" % v
    return None


def _rows(rest: str, answer: Any) -> List[Tuple[str, Any]]:
    """(row label, cell value) pairs of a ROW_TYPES answer, in answer order."""
    if rest == "SORTING":
        return [(label, rank) for rank, label in enumerate(_labels(answer), 1)]
    rows: List[Tuple[str, Any]] = []
    for item in _objects(answer):
        if not isinstance(item, dict):
            continue
        labels = _item_labels(item)
        if not labels:
            continue
        value = item.get("value")
        if rest == "SEMANTIC_DIFFERENTIAL":
            rows.append((PAIR_SEP.join(labels), _first(value)))
        elif rest == "MATRIX_MULTIPLE_CHOICE":
            rows.append((labels[0], MULTI_SEP.join(_leaves(value)) or None))
        elif rest == "MATRIX_TEXT" and isinstance(value, list):
            for col in value:
                if isinstance(col, dict):
                    rows.append((labels[0] + ROW_SEP + _clean(col.get("label")), col.get("value")))
        else:  # MATRIX_SINGLE_CHOICE, DIVIDE_POINTS (and a MATRIX_TEXT row given as a scalar)
            rows.append((labels[0], _first(value)))
    return rows


def _leaves(value: Any) -> List[str]:
    """Scalar leaf values of any nested dict/list, as text (never a Python repr)."""
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        return [x for v in value.values() for x in _leaves(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in _leaves(v)]
    return [str(value)]


def _readable(answer: Any) -> Any:
    """Any answer shape as text: each object `label: value`, its labels, or its value;
    other structures as their scalar leaves. Parts joined with ` | `; nothing -> empty."""
    parts = []
    for item in _objects(answer):
        if isinstance(item, dict) and ("labels" in item or "value" in item):
            labels = _item_labels(item)
            value = MULTI_SEP.join(_leaves(item.get("value")))
            if labels and value:
                parts.append("%s: %s" % (MULTI_SEP.join(labels), value))
            elif labels or value:
                parts.append(MULTI_SEP.join(labels) or value)
        else:
            parts += _leaves(item)
    return MULTI_SEP.join(parts) or None


def _cell(tsv_type: str, answer: Any) -> Any:
    if tsv_type in ("NPS", "RATING", "NUMBER"):
        v = _value(answer)
        if v is None:
            v = (_labels(answer) or [None])[0]
        return v
    if tsv_type == "CHOICE":
        labels = _labels(answer)
        return labels[0] if labels else _other(answer)
    if tsv_type == "MULTI":
        items = _labels(answer) + [x for x in [_other(answer)] if x]
        return MULTI_SEP.join(items) or None
    if tsv_type == "TEXT" and (answer is None or isinstance(answer, (str, int, float))):
        return answer
    v = _value(answer)  # TEXT given as an object: its `value`
    return v if v is not None else _readable(answer)


_START = object()  # no question precedes this one in the response


def _place(order: List[Any], qid: Any, prev: Any) -> None:
    """Questionnaire order from answer order (question ids follow creation order, not the
    questionnaire): a question first seen in a later response goes right after the question
    that precedes it in that response, or first when nothing precedes it."""
    order.insert(0 if prev is _START else order.index(prev) + 1, qid)


def build_columns(responses: List[dict]) -> Tuple[List[Column], dict]:
    """Columns for every question seen in any response, in questionnaire order (see
    _place), rows of ROW_TYPES questions in first-seen order. Second value: unmapped_types,
    email_questions, pipe_in_labels, duplicate_labels (qids whose label got a ` (n)` suffix:
    analyze.py keys questions by text, so a repeated label would merge two questions),
    responses_without_id (rows that `response_row` skips). In labels of row-based questions
    ` :: ` becomes ` : ` (header separator)."""
    questions: Dict[Any, Tuple[str, str, str]] = {}  # qid -> (REST type, TSV type, label)
    order: List[Any] = []
    rows: Dict[Any, List[str]] = {}
    unmapped, emails, pipes = set(), set(), set()
    without_id = 0
    for resp in responses:
        if _response_id(resp) is None:
            without_id += 1
            continue
        prev = _START
        for ans in resp.get("answers") or []:
            q = _question(ans)
            if q is None:
                continue
            qid, rest = q.get("id"), _rest_type(q)
            if rest in TYPE_MAP and TYPE_MAP[rest] is None:
                emails.add(qid)
                continue
            if rest not in TYPE_MAP:
                unmapped.add(rest)
            if qid not in questions:
                questions[qid] = (rest, TYPE_MAP.get(rest) or "TEXT", _clean(q.get("label")))
                _place(order, qid, prev)
            prev = qid
            rest, tsv_type = questions[qid][:2]
            answer = ans.get("answer")
            if rest in ROW_TYPES:
                seen = rows.setdefault(qid, [])
                for row, _ in _rows(rest, answer):
                    row = _clean(row)
                    if row not in seen:
                        seen.append(row)
                if rest == "MATRIX_MULTIPLE_CHOICE" and any(
                        MULTI_SEP in x for item in _objects(answer) if isinstance(item, dict)
                        for x in _leaves(item.get("value"))):
                    pipes.add(qid)
            elif tsv_type == "MULTI" and any(
                    MULTI_SEP in x for x in _labels(answer) + [_other(answer) or ""]):
                pipes.add(qid)
    columns, used, renamed = [], set(), []
    for qid in order:
        rest, tsv_type, label = questions[qid]
        if rest in ROW_TYPES:
            label = label.replace(ROW_SEP, " : ")
        unique, n = label, 1
        while unique.strip() in used:
            n += 1
            unique = "%s (%d)" % (label, n)
        if n > 1:
            renamed.append(qid)
        used.add(unique.strip())
        label = unique
        if rest in ROW_TYPES:
            columns += [Column(tsv_type, label, row, qid) for row in rows.get(qid, [])]
        else:
            columns.append(Column(tsv_type, label, None, qid))
    info = {"unmapped_types": sorted(unmapped), "email_questions": len(emails),
            "pipe_in_labels": sorted(pipes, key=_qid_key), "duplicate_labels": renamed,
            "responses_without_id": without_id}
    return columns, info


def _response_id(resp: dict) -> Any:
    rid = resp.get("responseId")
    if rid in (None, ""):
        rid = resp.get("id")
    return None if rid in (None, "") else rid


def response_row(resp: dict, columns: List[Column]) -> Optional[List[str]]:
    """[responseId, submitted, one cell per column], every cell plain text; None for a
    response without an id (counted in build_columns' responses_without_id)."""
    rid = _response_id(resp)
    if rid is None:
        return None
    types = {c.qid: c.type for c in columns}
    cells: Dict[Tuple[Any, Optional[str]], Any] = {}
    for ans in resp.get("answers") or []:
        q = _question(ans)
        if q is None or q.get("id") not in types:
            continue
        qid, answer, rest = q.get("id"), ans.get("answer"), _rest_type(q)
        if rest in ROW_TYPES:
            for row, value in _rows(rest, answer):
                cells.setdefault((qid, _clean(row)), value)
        elif rest not in TYPE_MAP:
            cells.setdefault((qid, None), _readable(answer))
        else:
            cells.setdefault((qid, None), _cell(types[qid], answer))
    return [_clean(rid), _clean(resp.get("submitted"))] + \
        [_clean(cells.get((c.qid, c.row))) for c in columns]


def write_page(path: Path, columns: List[Column], responses: List[dict]) -> None:
    """Header + one line per response (responses without an id skipped), UTF-8, `\\n` line
    ends, written atomically."""
    header = ["responseId", "submitted"] + [c.header() for c in columns]
    with atomic_writer(str(path)) as f:
        f.write("\t".join(header) + "\n")
        for resp in responses:
            row = response_row(resp, columns)
            if row is not None:
                f.write("\t".join(row) + "\n")
