#!/usr/bin/env python3
"""Deterministic survey analysis for Survio data (stdlib only — no numpy/scipy needed).

Input: a compact TSV written page by page from survio_list_survey_responses output (preferred —
see load_tsv), or JSON files shaped like the MCP output ({"responses": [...]}), or a directory. All numbers in a report should come from this script, so they are
reproducible and the anonymity rules (no metric for a group with n < 5) are applied consistently.

Commands (all accept --data PATH [PATH ...]; add --json for machine-readable output):
  profile                       n, columns (keys Q1, Q2, Q3.1 ...), types, answer rates, segments
  quality                       straight-liners, exact duplicates, gibberish, empty/non-answers,
                                completion-time outliers (if --times file given)
  nps     --q Q1 [--by Q5]      NPS / eNPS with 95% CI, optionally per segment (suppressed if n<5)
  summary --q Q2 [--by Q5]      mean / top-2-box / distribution of a rating or matrix row per segment
  compare --q Q2 --by Q5 --a X --b Y   two groups, four tests (chi2, Mann-Whitney, Welch t, bootstrap)
  segments --q Q2 --by Q5       every group vs. the rest (Holm-corrected), only n>=30 groups judged
  drivers --target Q1 [--q Q3.1 Q3.2 ...]   Spearman + promoter/detractor gap per attribute
  waves   --data A.json --data2 B.json --q Q2 ...   same questionnaire, two waves: shift + tests
  vw      --tc Q1 --ch Q2 --ex Q3 --te Q4 [--by Q5]  Van Westendorp price range (inconsistent rows excluded)
  text    --q Q7 [--out FILE]   export open answers (id, text, flags) for theme coding
  checkquote --q Q7 --quote "..."   verify a quote is verbatim in the data and screen it for PII
  moe     --n 120 [--p 0.5]     margin of error

Exclusions: --exclude FILE (one responseId per line) drops rows (e.g. after `quality`).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import unicodedata
from collections import Counter, OrderedDict

MIN_GROUP = 5          # anonymity: never report a metric for a group smaller than this
MIN_JUDGE = 30         # groups smaller than this are "too small to conclude", not findings
ALPHA = 0.05

# ----------------------------------------------------------------------------- stats (stdlib)


def _gammaincc(a, x):
    """Regularized upper incomplete gamma Q(a, x)."""
    if x <= 0:
        return 1.0
    if x < a + 1:
        s, term, n = 1.0 / a, 1.0 / a, a
        for _ in range(500):
            n += 1
            term *= x / n
            s += term
            if abs(term) < abs(s) * 1e-14:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    b, c, d = x + 1 - a, 1e300, 1 / (x + 1 - a)
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def chi2_sf(x, df):
    return _gammaincc(df / 2.0, x / 2.0) if df > 0 else 1.0


def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1e-300 if abs(d) < 1e-300 else d
    d = 1 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d; d = 1e-300 if abs(d) < 1e-300 else d
        c = 1 + aa / c; c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d; d = 1e-300 if abs(d) < 1e-300 else d
        c = 1 + aa / c; c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d; de = d * c; h *= de
        if abs(de - 1) < 1e-14:
            break
    return h


def betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_sf2(t, df):
    """Two-sided p for Student t."""
    if df <= 0 or math.isnan(t):
        return 1.0
    return betainc(df / 2, 0.5, df / (df + t * t))


def norm_sf2(z):
    return math.erfc(abs(z) / math.sqrt(2))


def mean(x):
    return sum(x) / len(x) if x else float("nan")


def var(x):
    if len(x) < 2:
        return 0.0
    m = mean(x)
    return sum((v - m) ** 2 for v in x) / (len(x) - 1)


def welch(a, b):
    va, vb, na, nb = var(a), var(b), len(a), len(b)
    if na < 2 or nb < 2:
        return 1.0
    se2 = va / na + vb / nb
    if se2 == 0:
        return 1.0 if mean(a) == mean(b) else 0.0
    t = (mean(a) - mean(b)) / math.sqrt(se2)
    df = se2 ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return t_sf2(t, df)


def rankdata(x):
    order = sorted(range(len(x)), key=lambda i: x[i])
    ranks = [0.0] * len(x)
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[order[j + 1]] == x[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def mannwhitney(a, b):
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return 1.0
    r = rankdata(list(a) + list(b))
    u = sum(r[:na]) - na * (na + 1) / 2
    n = na + nb
    ties = Counter(list(a) + list(b))
    tc = sum(t ** 3 - t for t in ties.values())
    sd = math.sqrt(na * nb / 12 * ((n + 1) - tc / (n * (n - 1)))) if n > 1 else 0
    if sd == 0:
        return 1.0
    z = (u - na * nb / 2 - 0.5 * (1 if u > na * nb / 2 else -1 if u < na * nb / 2 else 0)) / sd
    return norm_sf2(z)


def chi2_table(table):
    table = [row for row in table if sum(row) > 0]
    cols = [j for j in range(len(table[0])) if sum(r[j] for r in table) > 0] if table else []
    table = [[r[j] for j in cols] for r in table]
    if len(table) < 2 or len(cols) < 2:
        return 1.0
    tot = sum(map(sum, table))
    rs = [sum(r) for r in table]
    cs = [sum(r[j] for r in table) for j in range(len(cols))]
    x = sum((table[i][j] - rs[i] * cs[j] / tot) ** 2 / (rs[i] * cs[j] / tot)
            for i in range(len(table)) for j in range(len(cols)))
    return chi2_sf(x, (len(table) - 1) * (len(cols) - 1))


def spearman(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return float("nan")
    rx, ry = rankdata([p[0] for p in pairs]), rankdata([p[1] for p in pairs])
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def nps_of(scores):
    s = [v for v in scores if v is not None]
    if not s:
        return float("nan")
    return 100.0 * (sum(v >= 9 for v in s) - sum(v <= 6 for v in s)) / len(s)


def nps_ci(scores):
    s = [v for v in scores if v is not None]
    n = len(s)
    if n == 0:
        return (float("nan"),) * 2
    p, d = sum(v >= 9 for v in s) / n, sum(v <= 6 for v in s) / n
    se = math.sqrt(max(p + d - (p - d) ** 2, 0) / n) * 100
    return (100 * (p - d) - 1.96 * se, 100 * (p - d) + 1.96 * se)


def boot_p(a, b, stat, n=3000, seed=7):
    rnd = random.Random(seed)
    diffs = []
    for _ in range(n):
        diffs.append(stat([rnd.choice(a) for _ in a]) - stat([rnd.choice(b) for _ in b]))
    lo = sum(d <= 0 for d in diffs) / n
    hi = sum(d >= 0 for d in diffs) / n
    return max(min(1.0, 2 * min(lo, hi)), 1 / n)


def moe(n, p=0.5):
    return 100 * 1.96 * math.sqrt(p * (1 - p) / n) if n else float("nan")


def holm(ps):
    idx = sorted(range(len(ps)), key=lambda i: ps[i])
    out, m, running = [0.0] * len(ps), len(ps), 0.0
    for rank, i in enumerate(idx):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        out[i] = running
    return out


# ----------------------------------------------------------------------------- data loading


class Data:
    def __init__(self, responses):
        self.rows = []          # list of dict key -> value
        self.ids = []
        self.submitted = []
        self.cols = OrderedDict()   # key -> {"label", "type", "question", "row"}
        qn = 0
        qkey = {}
        for r in responses:
            for a in r.get("answers", []):
                q = a["question"]
                if q not in qkey:
                    qn += 1
                    qkey[q] = f"Q{qn}"
        for r in responses:
            row = {}
            for a in r.get("answers", []):
                k, t, v = qkey[a["question"]], a.get("type", ""), a.get("answer")
                if t.startswith("MATRIX"):
                    for cell in v or []:
                        label = (cell.get("labels") or [""])[0]
                        sub = self._sub(k, a["question"], label)
                        val = (cell.get("value") or [None])[0]
                        row[sub] = _num(val)
                elif t in ("NPS", "RATING", "NUMBER", "NUMERIC", "SCALE"):
                    self._reg(k, a["question"], t)
                    row[k] = _num(v)
                elif t in ("SINGLE_CHOICE", "DROPDOWN"):
                    self._reg(k, a["question"], t)
                    row[k] = v[0] if isinstance(v, list) and v else (v or None)
                elif t == "MULTIPLE_CHOICE":
                    self._reg(k, a["question"], t)
                    row[k] = tuple(v or [])
                else:
                    self._reg(k, a["question"], t or "TEXT")
                    row[k] = v if v not in ("", None) else None
                    if isinstance(row[k], (int, float)) and t not in ("TEXT",):
                        row[k] = _num(row[k])
            self.rows.append(row)
            self.ids.append(str(r.get("responseId")))
            self.submitted.append(r.get("submitted"))
        for k, c in self.cols.items():
            if c["type"] in ("TEXT", "") and all(isinstance(row.get(k), (int, float)) or row.get(k) is None for row in self.rows):
                if any(row.get(k) is not None for row in self.rows):
                    c["type"] = "NUMBER"

    def _reg(self, k, q, t):
        if k not in self.cols:
            self.cols[k] = {"label": q, "type": t, "question": q, "row": None}

    def _sub(self, k, q, label):
        for kk, c in self.cols.items():
            if c["question"] == q and c["row"] == label:
                return kk
        n = sum(1 for c in self.cols.values() if c["question"] == q) + 1
        kk = f"{k}.{n}"
        self.cols[kk] = {"label": f"{q} — {label}", "type": "MATRIX_ROW", "question": q, "row": label}
        return kk

    def col(self, k):
        if k not in self.cols:
            raise SystemExit(f"unknown column {k}; run `profile` to see keys")
        return [r.get(k) for r in self.rows]

    def filter(self, keep):
        d = Data.__new__(Data)
        d.cols = self.cols
        d.rows = [r for r, kp in zip(self.rows, keep) if kp]
        d.ids = [i for i, kp in zip(self.ids, keep) if kp]
        d.submitted = [s for s, kp in zip(self.submitted, keep) if kp]
        return d


def _num(v):
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", ".").replace(" ", ""))
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


TSV_TYPES = {"NPS": "NPS", "RATING": "RATING", "CHOICE": "SINGLE_CHOICE", "SINGLE_CHOICE": "SINGLE_CHOICE",
             "MULTI": "MULTIPLE_CHOICE", "MULTIPLE_CHOICE": "MULTIPLE_CHOICE", "TEXT": "TEXT",
             "NUMBER": "NUMBER", "MATRIX": "MATRIX_SINGLE_CHOICE"}


def load_tsv(path):
    """Compact input written page by page from MCP output (see SKILL.md, step 2):

    header:  responseId<TAB>submitted<TAB>[TYPE] question ...  — TYPE is the MCP answer type
             (NPS, RATING, CHOICE, MULTI, TEXT, NUMBER) or [MATRIX] question :: row label
    rows:    one response per line; empty cell = no answer; MULTI values joined with " | ";
             tabs/newlines inside text replaced by spaces.
    Returns MCP-shaped responses so the rest of the script is unchanged."""
    lines = [l.rstrip("\n") for l in open(path, encoding="utf-8") if l.strip()]
    header = lines[0].split("\t")
    cols = []
    for h in header[2:]:
        m = re.match(r"\s*\[(\w+)\]\s*(.*)$", h)
        if not m:
            raise SystemExit(f"bad TSV header cell (expected '[TYPE] question'): {h!r}")
        typ, rest = m.group(1).upper(), m.group(2)
        if typ not in TSV_TYPES:
            raise SystemExit(f"unknown type [{typ}] in header; use one of {sorted(TSV_TYPES)}")
        q, row = (rest.split(" :: ", 1) + [None])[:2] if typ == "MATRIX" else (rest, None)
        cols.append((TSV_TYPES[typ], q.strip(), row.strip() if row else None))
    out = []
    for ln in lines[1:]:
        cells = ln.split("\t") + [""] * len(header)
        answers, mats = [], {}
        for (typ, q, row), v in zip(cols, cells[2:]):
            v = v.strip()
            if typ == "MATRIX_SINGLE_CHOICE":
                if q not in mats:
                    mats[q] = {"question": q, "type": typ, "answer": []}
                    answers.append(mats[q])
                if v:
                    mats[q]["answer"].append({"labels": [row], "value": [v]})
                continue
            if v == "":
                val = None
            elif typ in ("SINGLE_CHOICE",):
                val = [v]
            elif typ == "MULTIPLE_CHOICE":
                val = [x.strip() for x in v.split(" | ") if x.strip()]
            elif typ in ("NPS", "RATING", "NUMBER"):
                val = _num(v)
            else:
                val = v
            answers.append({"question": q, "type": typ, "answer": val})
        out.append({"responseId": cells[0].strip(), "submitted": cells[1].strip() or None, "answers": answers})
    return out


def load(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith((".json", ".tsv")))
        else:
            files.append(p)
    resp, seen = [], set()
    for f in files:
        if f.endswith((".tsv", ".txt")):
            items = load_tsv(f)
        else:
            obj = json.load(open(f, encoding="utf-8"))
            items = obj["responses"] if isinstance(obj, dict) else obj
        for r in items:
            rid = r.get("responseId")
            if rid in seen:
                continue          # same response saved twice (overlapping pages) — not a duplicate respondent
            seen.add(rid)
            resp.append(r)
    resp.sort(key=lambda r: (r.get("submitted") or "", r.get("responseId") or 0))
    return Data(resp)


# ----------------------------------------------------------------------------- anonymity


def group_counts(data, by):
    return Counter(v for v in data.col(by) if v is not None)


def safe_groups(counts):
    """Apply small-cell rules. Returns (shown_groups, suppressed, merged_label or None).

    Groups with n < MIN_GROUP are never shown individually. If they can be merged into an
    'Other (merged)' group with n >= MIN_GROUP they are; otherwise the next-smallest group is
    suppressed too, so a hidden group can't be recovered by subtracting the shown groups from
    the total (secondary suppression)."""
    small = [g for g, n in counts.items() if n < MIN_GROUP]
    shown = [g for g, n in counts.items() if n >= MIN_GROUP]
    if not small:
        return shown, [], None
    if sum(counts[g] for g in small) >= MIN_GROUP and len(small) > 1:
        return shown, [], small
    extra = sorted(shown, key=lambda g: counts[g])[:1] if shown else []
    return [g for g in shown if g not in extra], small + extra, None


# ----------------------------------------------------------------------------- quality

KEYBOARD_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm", "qwertzuiop", "yxcvbnm"]
NONANSWERS = {"ok", "nic", "-", "--", ".", "..", "n/a", "na", "nevím", "nevim", "neviem", "nič", "nic.", "x", "no",
              "none", "nothing", "no comment", "idk", "nope", "nichts", "k.a.", "keine ahnung", "bez komentáře",
              "?", "nemám", "nemam", "passt", "nö", "bez pripomienok"}


def is_gibberish(t):
    s = (t or "").strip().lower()
    if len(s) < 3 or s in NONANSWERS:
        return False
    if re.fullmatch(r"[\d\s]{4,}", s):
        return True
    letters = re.sub(r"[^a-záčďéěíňóřšťúůýžäöüß]", "", s)
    if not letters:
        return False
    if re.fullmatch(r"(.)\1{3,}", letters):
        return True
    if any(letters in row * 2 or (len(letters) >= 5 and all(ch in row for ch in letters)) for row in KEYBOARD_ROWS):
        return True
    vowels = sum(ch in "aeiouyáéěíóúůýäöü" for ch in letters)
    words = s.split()
    if len(letters) >= 6 and vowels / len(letters) < 0.15:
        return True
    if s in {"lorem ipsum dolor", "test test", "asdf", "123123"} or re.fullmatch(r"[\d\s]{4,}", s):
        return True
    plain = [w for w in re.findall(r"[a-z]+", s) if len(w) >= 5]
    if plain and all(re.search(r"[bcdfghjklmnpqrstvwxz]{4,}", w) or not re.search(r"[aeiouy]", w) for w in plain) \
            and not re.search(r"[áčďéěíňóřšťúůýžäöüß]", s):
        return True
    if len(words) >= 2 and all(len(w) >= 3 and sum(c in "aeiouy" for c in w) == 0 for w in words):
        return True
    return False


_LETTERS = r"[^a-záčďéěíňóřšťúůýžäöüßłàâçèêëîïôùûœ ]"


def gibberish_outliers(texts, z=1.5):
    """Indexes of answers that look like random letters relative to the *other answers in the same
    question*: a character-bigram model is built from the column itself (so it works for any
    language mix), and an answer is flagged only if it is short (1–5 words, ≥6 letters) and every
    one of its words is an outlier. Catches strings like "umawnm bvswmv" that have vowels and slip
    past the rule-based checks in is_gibberish()."""
    words_by = [[w for w in re.sub(_LETTERS, "", (t or "").lower()).split() if len(w) >= 2] for t in texts]
    big, uni = Counter(), Counter()
    for ws in words_by:
        for w in ws:
            w = "^" + w + "$"
            for a, b in zip(w, w[1:]):
                big[a + b] += 1
                uni[a] += 1
    if len(uni) < 5:
        return set()
    V = len(uni) + 1

    def wscore(w):
        w = "^" + w + "$"
        return sum(math.log((big[a + b] + 0.5) / (uni[a] + 0.5 * V)) for a, b in zip(w, w[1:])) / (len(w) - 1)

    allw = [wscore(w) for ws in words_by for w in ws]
    if len(allw) < 30:
        return set()
    allw.sort()
    med = allw[len(allw) // 2]
    mad = sorted(abs(x - med) for x in allw)[len(allw) // 2] * 1.4826 or 1e-9
    return {i for i, ws in enumerate(words_by)
            if 1 <= len(ws) <= 5 and sum(map(len, ws)) >= 6 and all((med - wscore(w)) / mad > z for w in ws)}


def is_nonanswer(t):
    s = (t or "").strip().lower()
    if not s:
        return True
    if s in NONANSWERS:
        return True
    return not re.search(r"\w", s, re.UNICODE)  # emoji / punctuation only


def quality(data, times=None):
    ratings = [k for k, c in data.cols.items() if c["type"] == "MATRIX_ROW"]
    by_q = OrderedDict()
    for k in ratings:
        by_q.setdefault(data.cols[k]["question"], []).append(k)
    texts = [k for k, c in data.cols.items() if c["type"] == "TEXT"]
    flags = {i: set() for i in data.ids}
    # straight-lining: identical answer on every row of a matrix with >= 5 rows
    for q, keys in by_q.items():
        if len(keys) < 5:
            continue
        for rid, row in zip(data.ids, data.rows):
            vals = [row.get(k) for k in keys]
            if None not in vals and len(set(vals)) == 1:
                flags[rid].add("straight_liner")
    # exact duplicates: every answer identical to an earlier response. If the survey has open
    # text, require identical *substantive* text too — identical all-5 ratings with an empty
    # comment happen by chance; an identical sentence does not.
    # Without substantive text, identical answers can be pure coincidence (a 4-question survey with
    # 5-point scales repeats patterns all the time), so flag only patterns that are unlikely to
    # recur by chance: expected chance matches (n-1)·Π p(value) under independent marginals < 0.05.
    nonkeys = [k for k in data.cols if k not in texts]
    marg = {k: Counter(json.dumps(r.get(k), ensure_ascii=False, default=str) for r in data.rows) for k in nonkeys}
    n_rows = len(data.rows)

    def chance_matches(row):
        pr = 1.0
        for k in nonkeys:
            pr *= marg[k][json.dumps(row.get(k), ensure_ascii=False, default=str)] / max(n_rows, 1)
        return (n_rows - 1) * pr

    seen = {}
    for rid, row in zip(data.ids, data.rows):
        closed = [row.get(k) for k in ratings]
        has_text = any(row.get(k) and not is_nonanswer(row.get(k)) for k in texts)
        if not has_text and (len(set(closed)) <= 2 or chance_matches(row) >= 0.05):
            continue      # identical by chance is plausible
        sig = json.dumps([row.get(k) for k in data.cols], ensure_ascii=False, default=str)
        if sig in seen:
            flags[rid].add("duplicate_of:" + seen[sig])
        else:
            seen[sig] = rid
    # gibberish in any open text
    for rid, row in zip(data.ids, data.rows):
        if any(is_gibberish(row.get(k)) for k in texts):
            flags[rid].add("gibberish")
    for k in texts:  # statistical check against the other answers of the same question
        col = [row.get(k) for row in data.rows]
        for i in gibberish_outliers(col):
            flags[data.ids[i]].add("gibberish")
    # completion time (only if provided: JSON {responseId: seconds})
    if times:
        vals = sorted(v for v in times.values() if v)
        med = vals[len(vals) // 2] if vals else None
        for rid in data.ids:
            t = times.get(rid)
            if med and t is not None and t < med / 3:
                flags[rid].add("speeder")
    out = {"n": len(data.ids), "flags": {k: sorted(v) for k, v in flags.items() if v}}
    cnt = Counter()
    for v in out["flags"].values():
        for f in v:
            cnt[f.split(":")[0]] += 1
    out["counts"] = dict(cnt)
    out["n_flagged"] = len(out["flags"])
    out["nonanswer_rate"] = {k: round(sum(is_nonanswer(r.get(k)) for r in data.rows) / max(len(data.rows), 1), 3) for k in texts}
    out["note"] = ("Speeders need completion times; the Survio MCP response payload has none and its "
                   "completionTime filters may be unreliable — report speeders as 'not assessable' unless "
                   "times were provided via --times.") if not times else ""
    return out


# ----------------------------------------------------------------------------- PII screen

PII_PATTERNS = [
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "email"),
    (r"(\+?\d[\d ]{7,}\d)", "phone"),
    (r"\b(jedin[áýé]|only|einzige[rn]?|nejstarší|nejmladší|oldest|youngest)\b", "unique-role/demographic"),
    (r"\b(po|after|nach)\s+\d+\s+(letech|rokoch|years|jahren)\b", "tenure"),
    (r"\b(vedouc[íi]|team ?lead(er)?|manager|šéf|head of|leiter)\b", "role"),
    (r"(—|-)\s*[A-ZČŘŠŽÝÁÍÉ][a-zčřšžýáíéůú]+\s+[A-ZČŘŠŽ]\.?", "signature"),
    (r"\b(kolega|kolegyně|colleague|manager|vedoucí|šéf)\s+[A-ZČŘŠŽ][a-zčřšžýáíéůú]+", "named-person"),
    (r"\b[A-ZČŘŠŽ][a-zčřšžýáíéůú]+\s+[A-ZČŘŠŽ][a-zčřšžýáíéůúová]+(ová)?\b", "possible-name"),
]


def pii_hits(text):
    hits = []
    for pat, kind in PII_PATTERNS:
        for m in re.finditer(pat, text or ""):
            hits.append({"kind": kind, "match": m.group(0)})
    return hits


# ----------------------------------------------------------------------------- commands


def fmt(x, d=1):
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def cmd_profile(data, a):
    out = {"n": len(data.rows), "first": data.submitted[0] if data.submitted else None,
           "last": data.submitted[-1] if data.submitted else None, "columns": []}
    for k, c in data.cols.items():
        vals = data.col(k)
        answered = [v for v in vals if v not in (None, "", ())]
        col = {"key": k, "type": c["type"], "label": c["label"], "answered": len(answered),
               "answer_rate": round(len(answered) / max(len(vals), 1), 3)}
        if c["type"] in ("SINGLE_CHOICE", "DROPDOWN"):
            cnt = Counter(answered)
            col["groups"] = {g: n for g, n in cnt.most_common()}
            col["small_groups_n_lt_5"] = [g for g, n in cnt.items() if n < MIN_GROUP]
        elif c["type"] in ("NPS", "RATING", "MATRIX_ROW", "NUMBER"):
            nums = [v for v in answered if isinstance(v, (int, float))]
            if nums:
                col["min"], col["max"], col["mean"] = min(nums), max(nums), round(mean(nums), 2)
        elif c["type"] == "TEXT":
            col["non_answers"] = sum(is_nonanswer(v) for v in answered)
        out["columns"].append(col)
    return out


def cmd_nps(data, a):
    s = data.col(a.q)
    lo, hi = nps_ci(s)
    n = sum(v is not None for v in s)
    out = {"question": data.cols[a.q]["label"], "n": n, "nps": round(nps_of(s), 1), "ci95": [round(lo, 1), round(hi, 1)],
           "promoters": sum(v is not None and v >= 9 for v in s), "passives": sum(v is not None and 7 <= v <= 8 for v in s),
           "detractors": sum(v is not None and v <= 6 for v in s)}
    if a.by:
        out["by"] = segment_metric(data, a.by, lambda d: nps_of(d.col(a.q)), a.q, nps=True)
    return out


def segment_metric(data, by, metric, q, nps=False):
    counts = group_counts(data, by)
    shown, suppressed, merged = safe_groups(counts)
    groups = OrderedDict()
    for g in sorted(shown, key=lambda g: -counts[g]):
        sub = data.filter([v == g for v in data.col(by)])
        vals = [v for v in sub.col(q) if v is not None]
        groups[g] = {"n": len(vals), "value": round(metric(sub), 2),
                     "note": "n<30: descriptive only, too small to conclude" if len(vals) < MIN_JUDGE else ""}
        if nps:
            lo, hi = nps_ci(vals)
            groups[g]["ci95"] = [round(lo, 1), round(hi, 1)]
    if merged:
        sub = data.filter([v in merged for v in data.col(by)])
        groups["Other (merged small groups)"] = {"n": sum(counts[g] for g in merged), "value": round(metric(sub), 2),
                                                 "note": "merged for anonymity; members not listed"}
    return {"segment": data.cols[by]["label"], "groups": groups,
            "suppressed": {"count": len(suppressed),
                           "rule": f"groups with n<{MIN_GROUP} are not reported (plus secondary suppression so they can't be derived)"}}


def _vals(data, q):
    return [v for v in data.col(q) if isinstance(v, (int, float))]


def cmd_summary(data, a):
    def stats(d):
        v = _vals(d, a.q)
        hi = max(_vals(data, a.q) or [5])
        return {"n": len(v), "mean": round(mean(v), 2) if v else None,
                "top2_pct": round(100 * sum(x >= hi - 1 for x in v) / len(v), 1) if v else None,
                "dist": dict(sorted(Counter(v).items()))}
    out = {"question": data.cols[a.q]["label"], **stats(data)}
    if a.by:
        out["by"] = segment_metric(data, a.by, lambda d: mean(_vals(d, a.q)), a.q)
    return out


def four_tests(x, y, kind, scale_hi=5):
    if kind == "nps":
        cat = lambda v: 2 if v >= 9 else 1 if v >= 7 else 0
        table = [[sum(cat(v) == c for v in x) for c in range(3)], [sum(cat(v) == c for v in y) for c in range(3)]]
        stat = nps_of
        eff = nps_of(x) - nps_of(y)
    elif kind == "top2":
        x = [1 if v >= scale_hi - 1 else 0 for v in x]
        y = [1 if v >= scale_hi - 1 else 0 for v in y]
        table = [[sum(x), len(x) - sum(x)], [sum(y), len(y) - sum(y)]]
        stat = lambda s: 100 * mean(s)
        eff = stat(x) - stat(y)
    else:
        box = lambda v: 2 if v >= scale_hi - 1 else 0 if v <= 2 else 1
        table = [[sum(box(v) == c for v in x) for c in range(3)], [sum(box(v) == c for v in y) for c in range(3)]]
        stat = mean
        eff = mean(x) - mean(y)
    p = {"chi2": chi2_table(table), "mannwhitney": mannwhitney(x, y), "welch_t": welch(x, y),
         "bootstrap": boot_p(x, y, stat)}
    sig_all = all(v < ALPHA for v in p.values())
    sig_any = any(v < ALPHA for v in p.values())
    verdict = ("significant" if sig_all else "borderline (tests disagree)" if sig_any else "not significant")
    small = min(len(x), len(y)) < MIN_JUDGE
    if small and verdict != "not significant":
        if all(v < 0.01 for v in p.values()):
            verdict += f" (small group, n={min(len(x), len(y))}: strong evidence, but state the n)"
        else:
            verdict = f"inconclusive — a group has n<30 (n={min(len(x), len(y))}); treat as a hypothesis, not a finding"
    return {"effect": round(eff, 2), "n": [len(x), len(y)], "p": {k: round(v, 4) for k, v in p.items()},
            "verdict": verdict}


def cmd_compare(data, a):
    by = data.col(a.by)
    counts = group_counts(data, a.by)
    for g in (a.a, a.b):
        if counts.get(g, 0) < MIN_GROUP and g != "*rest*":
            return {"error": f"group '{g}' has n<{MIN_GROUP}: comparison suppressed for anonymity"}
    x = [v for v, g in zip(data.col(a.q), by) if g == a.a and v is not None]
    y = [v for v, g in zip(data.col(a.q), by) if (g == a.b or (a.b == "*rest*" and g != a.a)) and v is not None]
    kind = a.kind or ("nps" if data.cols[a.q]["type"] == "NPS" else "mean")
    return {"question": data.cols[a.q]["label"], "groups": [a.a, a.b], "kind": kind,
            **four_tests(x, y, kind, max(_vals(data, a.q) or [5]))}


def cmd_segments(data, a):
    counts = group_counts(data, a.by)
    shown, suppressed, merged = safe_groups(counts)
    kind = a.kind or ("nps" if data.cols[a.q]["type"] == "NPS" else "mean")
    by = data.col(a.by)
    res = []
    for g in shown:
        x = [v for v, gg in zip(data.col(a.q), by) if gg == g and v is not None]
        y = [v for v, gg in zip(data.col(a.q), by) if gg != g and v is not None]
        res.append({"group": g, **four_tests(x, y, kind, max(_vals(data, a.q) or [5]))})
    adj = holm([max(r["p"].values()) for r in res]) if res else []
    for r, p in zip(res, adj):
        r["p_holm_worst_test"] = round(p, 4)
        if p >= ALPHA and r["verdict"].startswith("significant"):
            r["verdict"] = "not significant after multiple-comparison correction"
    return {"question": data.cols[a.q]["label"], "segment": data.cols[a.by]["label"], "kind": kind,
            "vs_rest": res, "suppressed_groups": len(suppressed), "merged_small_groups": bool(merged)}


def cmd_drivers(data, a):
    tgt = data.col(a.target)
    keys = a.q or [k for k, c in data.cols.items() if c["type"] == "MATRIX_ROW" and k != a.target]
    is_nps = data.cols[a.target]["type"] == "NPS"
    out = []
    for k in keys:
        x = data.col(k)
        rho = spearman(x, tgt)
        row = {"key": k, "label": data.cols[k]["label"], "spearman": round(rho, 3),
               "mean": round(mean([v for v in x if v is not None]), 2)}
        if is_nps:
            pr = [v for v, t in zip(x, tgt) if v is not None and t is not None and t >= 9]
            de = [v for v, t in zip(x, tgt) if v is not None and t is not None and t <= 6]
            row["promoters_mean"], row["detractors_mean"] = round(mean(pr), 2), round(mean(de), 2)
            row["test"] = four_tests(pr, de, "mean")
        out.append(row)
    out.sort(key=lambda r: -abs(r["spearman"]) if not math.isnan(r["spearman"]) else 0)
    return {"target": data.cols[a.target]["label"], "drivers": out,
            "note": "A high average rating with no relation to the target is a strength, not a driver."}


def cmd_waves(a):
    d1, d2 = load(a.data), load(a.data2)
    out = {"n": [len(d1.rows), len(d2.rows)], "items": []}
    labels2 = {c["label"]: k for k, c in d2.cols.items()}
    keys = a.q or [k for k, c in d1.cols.items() if c["type"] in ("NPS", "RATING", "MATRIX_ROW")]
    for k in keys:
        lab = d1.cols[k]["label"]
        k2 = labels2.get(lab)
        if not k2:
            continue
        x, y = _vals(d2, k2), _vals(d1, k)
        kind = "nps" if d1.cols[k]["type"] == "NPS" else "mean"
        item = {"key": k, "label": lab, "kind": kind}
        if kind == "nps":
            item["wave1"], item["wave2"] = round(nps_of(y), 1), round(nps_of(x), 1)
        else:
            item["wave1"], item["wave2"] = round(mean(y), 2), round(mean(x), 2)
            hi = max(y + x or [5])
            item["top2_wave1"] = round(100 * sum(v >= hi - 1 for v in y) / len(y), 1)
            item["top2_wave2"] = round(100 * sum(v >= hi - 1 for v in x) / len(x), 1)
            item["top2_test"] = four_tests(x, y, "top2", hi)
        item["test"] = four_tests(x, y, kind)
        out["items"].append(item)
    if a.by:
        out["by_segment"] = {}
        for g in set(v for v in d1.col(a.by) if v):
            s1, s2 = d1.filter([v == g for v in d1.col(a.by)]), d2.filter([v == g for v in d2.col(labels2.get(d1.cols[a.by]["label"], a.by))])
            if len(s1.rows) < MIN_GROUP or len(s2.rows) < MIN_GROUP:
                continue
            res = {}
            for k in keys:
                k2 = labels2.get(d1.cols[k]["label"])
                if not k2:
                    continue
                kind = "nps" if d1.cols[k]["type"] == "NPS" else "mean"
                res[k] = four_tests(_vals(s2, k2), _vals(s1, k), kind)
            out["by_segment"][g] = res
    return out


def cmd_vw(data, a):
    rows = []
    for r, rid in zip(data.rows, data.ids):
        v = [r.get(a.tc), r.get(a.ch), r.get(a.ex), r.get(a.te)]
        rows.append((rid, v, r.get(a.by) if a.by else None))
    valid = [x for x in rows if None not in x[1]]
    bad = [x for x in valid if not (x[1][0] < x[1][1] < x[1][2] < x[1][3])]
    good = [x for x in valid if x not in bad]

    def curves(sample):
        tc, ch, ex, te = ([s[1][i] for s in sample] for i in range(4))
        lo, hi = min(tc + ch) * 0.8, max(ex + te) * 1.1
        grid = [lo + (hi - lo) * i / 3999 for i in range(4000)]
        n = len(sample)
        f = lambda arr, g, ge: sum((v >= g) if ge else (v <= g) for v in arr) / n
        c_tc = [f(tc, g, True) for g in grid]
        c_ch = [f(ch, g, True) for g in grid]
        c_ex = [f(ex, g, False) for g in grid]
        c_te = [f(te, g, False) for g in grid]

        def cross(u, w):
            for i in range(len(grid) - 1):
                d0, d1 = u[i] - w[i], u[i + 1] - w[i + 1]
                if d0 == 0:
                    return grid[i]
                if d0 * d1 < 0:
                    return grid[i] - d0 * (grid[i + 1] - grid[i]) / (d1 - d0)
            return float("nan")
        return {"PMC (lower bound)": round(cross(c_tc, [1 - x for x in c_ch]), 0),
                "OPP": round(cross(c_tc, c_te), 0),
                "IPP": round(cross(c_ch, c_ex), 0),
                "PME (upper bound)": round(cross(c_te, [1 - x for x in c_ex]), 0)}
    out = {"n_answered": len(valid), "excluded_inconsistent": len(bad),
           "excluded_ids": [x[0] for x in bad], "n_used": len(good), "price_points": curves(good),
           "convention": "PMC=too cheap∩not cheap, PME=too expensive∩not expensive, OPP=too cheap∩too expensive, IPP=cheap∩expensive (linear interpolation)"}
    if a.by:
        out["by"] = {}
        cnt = Counter(x[2] for x in good)
        for g, n in cnt.items():
            if n >= MIN_JUDGE:
                out["by"][g] = {"n": n, "price_points": curves([x for x in good if x[2] == g])}
            else:
                out["by"][g] = {"n": n, "note": "too few respondents for a stable price range" if n >= MIN_GROUP else "suppressed (n<5)"}
    absurd = [x[0] for x in good if max(x[1]) > 20 * sorted(s[1][3] for s in good)[len(good) // 2]]
    if absurd:
        out["warning_absurd_values"] = absurd
    return out


def cmd_text(data, a):
    rows = []
    outl = {data.ids[i] for i in gibberish_outliers([r.get(a.q) for r in data.rows])}
    for rid, r in zip(data.ids, data.rows):
        t = r.get(a.q)
        if t in (None, ""):
            continue
        rows.append({"id": rid, "text": t, "nonanswer": is_nonanswer(t), "gibberish": is_gibberish(t) or rid in outl,
                     "pii_flags": sorted({h["kind"] for h in pii_hits(t)})})
    out = {"question": data.cols[a.q]["label"], "n_answers": len(rows),
           "n_substantive": sum(not r["nonanswer"] and not r["gibberish"] for r in rows), "answers": rows}
    if a.out:
        json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return {k: v for k, v in out.items() if k != "answers"} | {"written": a.out}
    return out


def cmd_checkquote(data, a):
    texts = [r.get(a.q) or "" for r in data.rows] if a.q else [str(v) for r in data.rows for v in r.values() if isinstance(v, str)]
    found = any(a.quote in t for t in texts)
    hits = pii_hits(a.quote)
    return {"verbatim": found, "pii_flags": hits,
            "ok_to_quote": found and not hits,
            "advice": "" if found and not hits else
            ("not found verbatim — quote exactly or paraphrase" if not found else "may identify a person — paraphrase instead of quoting")}


ROLE_NOUNS = (r"(engineer|designer|developer|dev|devops|tester|qa|analyst|accountant|lawyer|lead|manager|director|"
              r"receptionist|recepční|masseuse|masér\w*|therapist|stylist|hairdresser|kadeřn\w+|admin\w*|intern|"
              r"specialist|consultant|recruiter|marketer|copywriter|person|woman|man|mother|mum|mom|parent|"
              r"inženýr\w*|designér\w*|vývojář\w*|programátor\w*|účetní|právni\w*|žena|muž|matk\w+|člověk)")
REPORT_ROLE_PATTERNS = [
    # self-descriptions that single a person out, as they tend to get restated in report prose
    (r"\b(the only|only|jedin[áýé]|jediný|einzige[rn]?)\s+(?![\d…])((?!a handful|one\b)[\w-]+\s+){0,3}?" + ROLE_NOUNS + r"s?\b[^.;\n\")“”]{0,30}",
     "unique role/demographic"),
    (r"\b(oldest|youngest|nejstarší|nejmladší)\s+[^.;\n]{0,40}", "oldest/youngest"),
    (r"\b(woman|man|person|žena|muž)\s+(over|aged|nad|ve věku)\s+\d{2}\b", "age"),
    (r"\b(lead|head of \w+|vedouc[íi]\w*|manager)\b[^.\n]{0,25}\b\d+\s+(years|let|roky|rokov)\b", "role + tenure"),
    (r"\b(after|po)\s+\d+\s+(years|letech)\s+(as|jako)\b[^.\n]{0,30}", "role + tenure"),
]


def cmd_checkreport(data, a):
    """Lint a finished report against the anonymity rules, using the data it was written from."""
    report = open(a.report, encoding="utf-8").read()
    lines = report.splitlines()
    issues = []

    def where(pos):
        return report.count("\n", 0, pos) + 1

    # 1. groups with n < MIN_GROUP: no exact size, no metric next to the group name
    for k, c in data.cols.items():
        if c["type"] not in ("SINGLE_CHOICE", "DROPDOWN"):
            continue
        cnt = Counter(v for v in data.col(k) if v not in (None, "", ()))
        for g, n in cnt.items():
            if n >= MIN_GROUP or len(str(g)) < 3:
                continue
            for m in re.finditer(re.escape(str(g)), report, flags=re.I):
                ln = lines[where(m.start()) - 1]
                if re.search(r"(\+|&|\bmerged\b|\bpooled\b|sloučen|\bother\b|ostatn)", ln, flags=re.I):
                    continue  # line talks about a merged group
                if re.search(rf"(?<![\d.,])({n})(?![\d.,%])", ln) and not re.search(r"fewer than|less than|méně než|<\s*5", ln, flags=re.I) or \
                        re.search(rf"\bn\s*=\s*{n}\b", ln):
                    issues.append({"kind": "exact size of a group with n<5", "group": g, "line": where(m.start()),
                                   "fix": "write 'fewer than 5' instead of the exact number"})
                if re.search(r"[+−-]?\d+([.,]\d+)?\s*%|[+−]\d+|\b\d[.,]\d+\b", ln):
                    issues.append({"kind": "possible metric for a group with n<5", "group": g, "line": where(m.start()),
                                   "fix": "remove the number or merge the group (n≥5) — check the line"})
    # 2. emails / phones from the data
    for m in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d ]{7,}\d", report):
        issues.append({"kind": "email/phone in report", "text": m.group(0), "line": where(m.start()), "fix": "remove it"})
    # 3. word sequences copied from answers that contain identifying details
    rep_f = " ".join(re.findall(r"\w+", report.lower()))
    for r in data.rows:
        for k, c in data.cols.items():
            v = r.get(k)
            if c["type"] != "TEXT" or not isinstance(v, str):
                continue
            kinds = {h["kind"] for h in pii_hits(v)} - {"possible-name", "role"}
            if not kinds:
                continue
            w = re.findall(r"\w+", v.lower())
            for i in range(len(w) - 4):
                gram = " ".join(w[i:i + 5])
                if gram in rep_f:
                    issues.append({"kind": "text from an identifying answer", "text": gram, "flags": sorted(kinds),
                                   "fix": "don't quote or closely paraphrase this answer; count its themes only"})
                    break
    # 4. identifying descriptions restated in the report's own words (any section, incl. caveats)
    for pat, kind in REPORT_ROLE_PATTERNS:
        for m in re.finditer(pat, report, flags=re.I):
            if re.search(r"\b[XY]\b|…", m.group(0)):
                continue  # generic placeholder ("the only person of type X in team Y")
            issues.append({"kind": f"identifying description ({kind})", "text": m.group(0).strip(), "line": where(m.start()),
                           "fix": "say generically 'some comments contain unique role/tenure details' — never the detail itself, not even as an example of what wasn't quoted"})
    seen, out = set(), []
    for i in issues:
        key = (i["kind"], i.get("group") or i.get("text"), i.get("line"))
        if key not in seen:
            seen.add(key)
            out.append(i)
    return {"ok": not out, "issues": out,
            "note": "Some flags can be false positives (e.g. 'only 3 of 10' about a large group); fix or consciously dismiss each one."}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd")
    ap.add_argument("--data", nargs="+")
    ap.add_argument("--data2", nargs="+")
    ap.add_argument("--q", nargs="*")
    ap.add_argument("--by")
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--kind", choices=["nps", "mean", "top2"])
    ap.add_argument("--target")
    ap.add_argument("--tc"); ap.add_argument("--ch"); ap.add_argument("--ex"); ap.add_argument("--te")
    ap.add_argument("--quote")
    ap.add_argument("--report")
    ap.add_argument("--out")
    ap.add_argument("--times")
    ap.add_argument("--exclude")
    ap.add_argument("--n", type=int)
    ap.add_argument("--p", type=float, default=0.5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "moe":
        res = {"n": a.n, "moe_95_pct_points": round(moe(a.n, a.p), 1)}
    elif a.cmd == "waves":
        res = cmd_waves(a)
    else:
        data = load(a.data)
        if a.exclude:
            drop = {l.strip() for l in open(a.exclude) if l.strip()}
            data = data.filter([i not in drop for i in data.ids])
        if a.cmd in ("summary", "nps", "compare", "segments", "text") and a.q and len(a.q) > 1:
            # several questions at once: run the command per question
            qs, res = a.q, {}
            for q in qs:
                a.q = q
                res[q] = {"summary": cmd_summary, "nps": cmd_nps, "compare": cmd_compare,
                          "segments": cmd_segments, "text": cmd_text}[a.cmd](data, a)
            print(json.dumps(res, ensure_ascii=False, indent=None if a.json else 1, default=str))
            return
        if a.q is not None and len(a.q) == 1 and a.cmd not in ("drivers",):
            a.q = a.q[0]
        times = json.load(open(a.times)) if a.times else None
        res = {"profile": lambda: cmd_profile(data, a), "quality": lambda: quality(data, times),
               "nps": lambda: cmd_nps(data, a), "summary": lambda: cmd_summary(data, a),
               "compare": lambda: cmd_compare(data, a), "segments": lambda: cmd_segments(data, a),
               "drivers": lambda: cmd_drivers(data, a), "vw": lambda: cmd_vw(data, a),
               "text": lambda: cmd_text(data, a), "checkquote": lambda: cmd_checkquote(data, a),
               "checkreport": lambda: cmd_checkreport(data, a)}[a.cmd]()
    print(json.dumps(res, ensure_ascii=False, indent=None if a.json else 1, default=str))


if __name__ == "__main__":
    main()
