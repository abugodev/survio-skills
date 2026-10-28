"""`responses +fetch`: every response of a survey into a survey-analyst workspace.

Writes `page_<N>.tsv` (one per API page, the format of SKILL.md step 2) and
`.survio/manifest.json`.
The manifest and the return value hold counts, ids and query parameters only: never answer
text, respondent emails or `parameters`.
"""
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple
from urllib.parse import quote

from .. import __version__
from ..client import Client
from ..errors import ApiError
from ..output import atomic_writer
from ..tsv import TYPE_MAP, build_columns, write_page

DROPPED_FIELDS = ["email", "parameters", "id"]
DATA_SUFFIXES = (".json", ".tsv")  # what analyze.load reads from the top level
MANIFEST_DIR = ".survio"

RowRule = Callable[[dict], Tuple[str, bool]]


def _dedupe_key(resp: dict) -> Any:
    """responseId; `id` only for a response without responseId; None = cannot dedupe."""
    for key in ("responseId", "id"):
        value = resp.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def manifest_path(ws: Path) -> Path:
    """In a subfolder: analyze.py reads every top-level .json/.tsv of the workspace as data."""
    return Path(ws) / MANIFEST_DIR / "manifest.json"


def _write_manifest(ws: Path, manifest: dict) -> None:
    path = manifest_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_writer(str(path)) as f:  # temp file .survio-*.tmp lands next to it
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _move_stale_files(ws: Path, written: set) -> None:
    """Top-level .json/.tsv files this run did not write (earlier pages, an MCP-route run's JSON)
    go to previous/, never deleted: analyze.load would merge them into the data."""
    stale = [p for p in sorted(ws.iterdir())
             if p.suffix in DATA_SUFFIXES and p.name not in written and p.is_file()]
    if not stale:
        return
    previous = ws / "previous"
    previous.mkdir(exist_ok=True)
    for p in stale:
        target, n = previous / p.name, 0
        while target.exists():
            n += 1
            target = previous / ("%s.%d" % (p.name, n))
        os.replace(str(p), str(target))


def rule_name(rule: RowRule, index: int) -> str:
    """The name recorded in the manifest: the rule's `name`, else its `__name__`."""
    return str(getattr(rule, "name", None) or getattr(rule, "__name__", None) or "rule_%d" % index)


def run_fetch(
    client: Client,
    survey_id: str,
    ws: Path,
    query: dict,
    row_rules: Sequence[RowRule] = (),
) -> dict:
    """Fetch all pages of the survey's responses into `ws`; return the manifest (also written to
    ws/.survio/manifest.json, with complete=false until every page file is in place)."""
    ws = Path(ws)
    ws.mkdir(parents=True, exist_ok=True)
    query = dict(query)
    rule_names = [rule_name(rule, i) for i, rule in enumerate(row_rules)]
    rule_dropped = [0] * len(row_rules)
    manifest = {
        "surveyId": survey_id, "route": "cli", "cli_version": __version__, "query": query,
        "pages": 0, "counts": {"received": 0, "responses": 0, "duplicates": 0, "questions": 0},
        "type_map": dict(TYPE_MAP), "unmapped_types": [], "pipe_in_labels": [],
        "duplicate_labels": [], "responses_without_id": 0,
        "dropped": {"email_questions": 0, "fields": list(DROPPED_FIELDS)},
        "row_rules": [], "complete": False,
    }  # type: Dict[str, Any]
    # an aborted run must not look like a finished one
    _write_manifest(ws, manifest)

    path = "/api/survey/%s/responses" % quote(str(survey_id), safe="")
    pages = []  # type: List[Tuple[int, List[dict]]]
    seen = set()
    received = duplicates = 0
    previous_items = None  # type: Any
    for page_no, items in client.paginate_pages(path, query=query, page_limit=0):
        if not all(isinstance(resp, dict) for resp in items):
            raise ApiError("expected an array of response objects (page %d)" % page_no)
        keys = [_dedupe_key(resp) for resp in items]
        # an API that ignores `page` would make this loop forever: a page that brings no new
        # responseId (or, without ids, repeats the previous page) ends the run, incomplete
        if not any(k is not None and k not in seen for k in keys) and (
                any(k is not None for k in keys) or items == previous_items):
            raise ApiError("API repeated a page (page %d brought no new responses); "
                           "the download is incomplete" % page_no)
        previous_items = items
        kept = []
        for resp, key in zip(items, keys):
            received += 1
            if key is not None:
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
            keep = True
            for i, rule in enumerate(row_rules):
                _, keep = rule(resp)
                if not keep:
                    rule_dropped[i] += 1
                    break
            if keep:
                kept.append(resp)
        pages.append((page_no, kept))
    if not pages:
        pages = [(1, [])]  # 0 responses: one header-only page

    every = [r for _, kept in pages for r in kept]
    columns, info = build_columns(every)
    written = set()
    for page_no, kept in pages:
        name = "page_%d.tsv" % page_no
        write_page(ws / name, columns, kept)
        written.add(name)
    _move_stale_files(ws, written)

    manifest.update({
        "pages": len(pages),
        "counts": {"received": received, "responses": len(every) - info["responses_without_id"],
                   "duplicates": duplicates, "questions": len({c.qid for c in columns})},
        "unmapped_types": info["unmapped_types"], "pipe_in_labels": info["pipe_in_labels"],
        "duplicate_labels": info["duplicate_labels"],
        "responses_without_id": info["responses_without_id"],
        "dropped": {"email_questions": info["email_questions"], "fields": list(DROPPED_FIELDS)},
        "row_rules": [{"rule": n, "dropped": d} for n, d in zip(rule_names, rule_dropped)],
        "complete": True,
    })
    _write_manifest(ws, manifest)
    return manifest


def warning_line(manifest: dict) -> str:
    """One stderr line naming question ids/types that need a look; empty when nothing does."""
    parts = []
    if manifest.get("duplicate_labels"):
        parts.append("questions %s share a label with another question (renamed with ' (n)')"
                     % ", ".join(str(q) for q in manifest["duplicate_labels"]))
    if manifest.get("pipe_in_labels"):
        parts.append("questions %s have ' | ' inside a choice label (MULTI cells are ambiguous)"
                     % ", ".join(str(q) for q in manifest["pipe_in_labels"]))
    if manifest.get("unmapped_types"):
        parts.append("types %s were written as TEXT" % ", ".join(manifest["unmapped_types"]))
    return ("warning: %s; see .survio/manifest.json" % "; ".join(parts)) if parts else ""
