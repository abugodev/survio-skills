"""Declarative command framework: an Op describes one API call; register/run turn it into a CLI."""
import argparse
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from .client import Client
from .errors import UsageError
from .output import atomic_writer, emit, emit_line

PARAM_TYPES = ("string", "integer", "number", "boolean", "json", "flag")


@dataclass
class Param:
    name: str  # the API's name (e.g. "sourceId[]"); also the key sent
    flag: str
    type: str = "string"
    required: bool = False
    help: str = ""
    choices: Optional[list] = None
    repeat: bool = False
    default: Any = None  # used when the flag is not given


@dataclass
class Op:
    resource: str
    name: str
    method: str
    path: str
    write: bool
    op_id: str  # the OpenAPI operationId
    help: str
    path_params: List[str] = field(default_factory=list)
    query: List[Param] = field(default_factory=list)
    body: List[Param] = field(default_factory=list)
    paged: bool = False
    build_body: Optional[Callable[[argparse.Namespace], dict]] = None
    # flag-only helpers that are not API fields (registered, but not part of the schema)
    extra: List[Param] = field(default_factory=list)
    # positional metavar per path parameter (default: the upper-cased name)
    path_metavars: Dict[str, str] = field(default_factory=dict)

    @property
    def has_body(self) -> bool:
        return bool(self.body) or self.build_body is not None


def _json_value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError("not valid JSON: %s" % e)


def _bool_value(text: str) -> bool:
    low = text.lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError("expected true or false, got %r" % text)


_CONVERTERS = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": _bool_value,
    "json": _json_value,
}  # "flag" has no converter: it is a store_const switch


def dest(kind: str, param: Param) -> str:
    return "%s_%s" % (kind, param.name)


def add_param(parser: argparse.ArgumentParser, kind: str, param: Param) -> None:
    if param.type not in PARAM_TYPES:
        raise ValueError("unknown param type %r" % param.type)
    if param.type == "flag":  # bare switch: True when given, else unset
        parser.add_argument(param.flag, dest=dest(kind, param), action="store_const", const=True,
                            default=None, help=param.help or None)
        return
    kwargs = {"dest": dest(kind, param), "default": param.default, "type": _CONVERTERS[param.type],
              "help": param.help or None, "metavar": param.type.upper()}
    if param.choices:
        kwargs["choices"] = param.choices
        kwargs["metavar"] = "{%s}" % ",".join(str(c) for c in param.choices) \
            if len(param.choices) <= 4 else param.type.upper()
    if param.repeat:
        kwargs["action"] = "append"
    parser.add_argument(param.flag, **kwargs)


def register(subparsers, ops: List[Op]) -> Dict[str, Any]:
    """Add one subparser per resource and one sub-subparser per op; return the per-resource subparsers."""
    resources = {}  # type: Dict[str, Any]
    for op in ops:
        if op.resource not in resources:
            rp = subparsers.add_parser(op.resource, help="%s commands" % op.resource)
            resources[op.resource] = rp.add_subparsers(
                dest="%s_command" % op.resource, parser_class=type(rp), metavar="<command>"
            )
        sp = resources[op.resource].add_parser(
            op.name,
            help=op.help,
            description="%s\n\nEndpoint: %s %s (%s, operation: %s)"
            % (op.help, op.method, op.path, "write" if op.write else "read", op.op_id),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        for pname in op.path_params:
            sp.add_argument("pp_" + pname, metavar=op.path_metavars.get(pname, pname.upper()))
        for param in op.query:
            add_param(sp, "q", param)
        for param in op.body:
            add_param(sp, "b", param)
        for param in op.extra:
            add_param(sp, "x", param)
        if op.has_body:
            sp.add_argument("--json", dest="json_body", default=None, metavar="JSON|@FILE",
                            help="request body as a JSON object or @file; explicit flags override it")
        if op.write:
            sp.add_argument("--dry-run", dest="dry_run", action="store_true",
                            help="print the request that would be sent, send nothing")
        if op.paged:
            sp.add_argument("--page", dest="page", type=int, default=None, metavar="N",
                            help="page number to fetch (default 1); with --page-all, the first page")
            sp.add_argument("--page-all", dest="page_all", action="store_true",
                            help="fetch page after page and print one JSON line (an array) per page")
            sp.add_argument("--page-limit", dest="page_limit", type=int, default=10, metavar="N",
                            help="maximum pages with --page-all (default 10, 0 = unlimited)")
        if op.paged or op.query:
            sp.add_argument("--query", dest="raw_query", action="append", default=[], metavar="KEY=VALUE",
                            help="extra query parameter, passed through as given (repeatable; "
                                 "explicit flags win)")
        sp.add_argument("--out", default=None, metavar="FILE", help="write the JSON result to FILE")
        sp.set_defaults(op=op)
    return resources


def _load_json_arg(text: str) -> dict:
    if text.startswith("@"):
        try:
            with open(text[1:], "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise UsageError("cannot read %s: %s" % (text[1:], e.strerror or e))
    try:
        value = json.loads(text)
    except ValueError as e:
        raise UsageError("--json is not valid JSON: %s" % e)
    if not isinstance(value, dict):
        raise UsageError("--json must be a JSON object")
    return value


def raw_query(pairs: List[str]) -> dict:
    """--query KEY=VALUE entries; a key given more than once becomes a list (repeated key)."""
    raw = {}  # type: Dict[str, Any]
    for item in pairs or []:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise UsageError("--query expects KEY=VALUE, got %r" % item)
        if key in raw:
            raw[key] = (raw[key] if isinstance(raw[key], list) else [raw[key]]) + [value]
        else:
            raw[key] = value
    return raw


def _query_of(op: Op, args) -> dict:
    query = raw_query(getattr(args, "raw_query", None))
    for p in op.query:
        value = getattr(args, dest("q", p), None)
        if value is not None:
            query[p.name] = value
        elif p.required and p.name not in query:
            raise UsageError("missing required: %s" % p.flag)
    page = getattr(args, "page", None)
    if page is not None:
        query["page"] = page
    if "page" in query:
        raw_page = query["page"]
        try:
            ok = not isinstance(raw_page, list) and int(raw_page) >= 1
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise UsageError("page must be a positive integer, got %r" % (raw_page,))
        query["page"] = int(raw_page)
    return query


def _body_of(op: Op, args) -> Optional[dict]:
    if not op.has_body:
        return None
    body = {}  # type: dict
    raw = getattr(args, "json_body", None)
    json_obj = _load_json_arg(raw) if raw is not None else {}
    args.json_obj = json_obj  # build_body callbacks read it to combine with the flags
    body.update(json_obj)
    if op.build_body is not None:
        body.update(op.build_body(args))
    else:
        for p in op.body:
            value = getattr(args, dest("b", p), None)
            if value is not None:
                body[p.name] = value
    missing = [p.flag for p in op.body if p.required and p.name not in body]
    if missing:
        raise UsageError("missing required: %s (or supply it via --json)" % ", ".join(missing))
    return body


def run(op: Op, args, client: Client) -> int:
    path = op.path
    for pname in op.path_params:
        value = str(getattr(args, "pp_" + pname))
        if value in (".", ".."):  # quote() keeps dots, and the URL would resolve to another endpoint
            raise UsageError("%s must not be '.' or '..'" % op.path_metavars.get(pname, pname.upper()))
        path = path.replace("{%s}" % pname, quote(value, safe=""))
    query = _query_of(op, args)
    body = _body_of(op, args)
    out = getattr(args, "out", None)
    if op.paged and getattr(args, "page_all", False):
        page_limit = getattr(args, "page_limit", 10)
        if page_limit < 0:
            raise UsageError("--page-limit must be 0 or more")
        start = query.pop("page", None)
        pages = client.paginate_pages(path, query=query, page_limit=page_limit,
                                      start_page=int(start) if start is not None else 1)
        if out:
            with atomic_writer(out) as f:  # nothing lands unless every page was fetched
                for _, items in pages:
                    emit_line(items, stream=f)
        else:
            for _, items in pages:
                emit_line(items)
        return 0
    result = client.request(
        op.method, path, query=query, body=body, write=op.write,
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    emit(result, out=out)
    return 0
