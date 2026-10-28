import sys
from pathlib import Path

from ..client import Client
from ..config import load_config
from ..errors import UsageError
from ..helpers import fetch
from ..ops import Op, Param, add_param, dest, raw_query
from ..output import emit

SOURCES = ["FB_WALL", "EMAIL", "TWITTER", "WEB_LINK", "IFRAME", "DIRECT", "CINT", "POPUP",
           "LINKEDIN", "GPLUS", "VKONTAKTE", "QR_CODE", "POPOVER", "WHATSAPP", "SOC_NETWORK", "IN_APP"]

# the filter flags; the names are the API's query parameters. +fetch reuses them.
FILTER_PARAMS = [
    Param("sourceId[]", "--source", choices=SOURCES, repeat=True,
          help="only responses from this collector source (repeatable)"),
    Param("langCode[]", "--lang", repeat=True, help="only responses in this language code, e.g. en (repeatable)"),
    Param("submitted_at[after]", "--submitted-after", help="submitted at or after this date/time"),
    Param("submitted_at[before]", "--submitted-before", help="submitted at or before this date/time"),
    Param("submitted_at[strictly_after]", "--submitted-strictly-after", help="submitted after this date/time"),
    Param("submitted_at[strictly_before]", "--submitted-strictly-before",
          help="submitted before this date/time"),
    Param("completion_time[greater_than]", "--completion-time-min", type="integer",
          help="completion time of at least this many seconds"),
    Param("completion_time[lower_than]", "--completion-time-max", type="integer",
          help="completion time of at most this many seconds"),
    Param("completion_time[strictly_greater_than]", "--completion-time-above", type="integer",
          help="completion time of more than this many seconds"),
    Param("completion_time[strictly_lower_than]", "--completion-time-below", type="integer",
          help="completion time of less than this many seconds"),
    Param("completion_time[equal]", "--completion-time-exact", type="integer",
          help="completion time of exactly this many seconds"),
    Param("order[submitted_at]", "--order", choices=["asc", "desc"], help="sort by submission time"),
]

OPS = [
    Op("responses", "list", "GET", "/api/survey/{id}/responses", False, "list_survey_responses",
       "list the responses of a survey (one page; --page-all for every page)",
       path_params=["id"], path_metavars={"id": "SURVEY_ID"}, query=FILTER_PARAMS, paged=True),
]


def _fetch_handler(args) -> int:
    if args.survey_id in (".", ".."):
        raise UsageError("SURVEY_ID must not be '.' or '..'")
    query = raw_query(args.raw_query)
    if "page" in query:
        raise UsageError("+fetch reads every page; it takes no page parameter")
    for p in FILTER_PARAMS:
        value = getattr(args, dest("q", p), None)
        if value is not None:
            query[p.name] = value
    query.setdefault("order[submitted_at]", "asc")
    manifest = fetch.run_fetch(Client(load_config()), args.survey_id, Path(args.ws), query)
    warning = fetch.warning_line(manifest)
    if warning:
        print(warning, file=sys.stderr)
    emit({"responses": manifest["counts"]["responses"], "pages": manifest["pages"]})
    return 0


def register_helpers(subparsers) -> None:
    sp = subparsers.add_parser(
        "+fetch", help="fetch every response of a survey into a survey-analyst workspace",
        description="Write page_<N>.tsv (one per API page, the survey-analyst TSV) and "
                    ".survio/manifest.json into --ws. Respondent emails, parameters and EMAIL questions "
                    "are left out. Prints counts only. Default order: submitted_at ascending.")
    sp.add_argument("survey_id", metavar="SURVEY_ID")
    sp.add_argument("--ws", required=True, metavar="DIR", help="workspace directory")
    for param in FILTER_PARAMS:
        add_param(sp, "q", param)
    sp.add_argument("--query", dest="raw_query", action="append", default=[], metavar="KEY=VALUE",
                    help="extra query parameter, passed through as given (repeatable; "
                         "explicit flags win)")
    sp.set_defaults(handler=_fetch_handler)
