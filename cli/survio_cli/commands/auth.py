"""`auth setup` (store the token) and `auth check` (probe the token); not Ops: local or token-aware."""
import getpass
import os
import sys
import tempfile
from pathlib import Path
from typing import List

from ..client import Client
from ..config import config_path, load_config
from ..errors import AuthError, CliError, UsageError, reason_of
from ..output import emit

TOKEN_VAR = "SURVIO_API_TOKEN"


def _updated_lines(existing: str, token: str) -> str:
    new_line = "%s=%s" % (TOKEN_VAR, token)
    lines = existing.splitlines()
    out = []  # type: List[str]
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export ") or stripped.startswith("export\t"):
            stripped = stripped[len("export"):].lstrip()
        if stripped.partition("=")[0].strip() == TOKEN_VAR and "=" in stripped:
            if not replaced:
                out.append(new_line)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append(new_line)
    return "\n".join(out) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    # a symlinked config stays a link: write the file it points to
    target = Path(os.path.realpath(str(path)))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(str(path.parent), 0o700)  # tighten an existing directory; never delete anything
    except PermissionError:
        print("warning: could not set %s to mode 0700 (not the owner?); continuing" % path.parent,
              file=sys.stderr)
    path = target
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _setup_handler(args) -> int:
    if not sys.stdin.isatty():
        raise UsageError("auth setup needs an interactive terminal; the token is never read from arguments or pipes")
    token = getpass.getpass("Survio API token: ").strip()
    if not token:
        raise UsageError("no token entered")
    path = config_path(os.environ)
    try:
        try:
            existing = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        _write_atomic(path, _updated_lines(existing, token))
    except (OSError, UnicodeDecodeError) as e:
        what = e.strerror if isinstance(e, OSError) and e.strerror else type(e).__name__
        raise CliError("cannot update the config file %s: %s" % (path, what))
    emit({"ok": True, "path": str(path)})
    return 0


def _check_handler(args) -> int:
    client = Client(load_config())
    try:
        client.request("GET", "/api/survey", query={"page": 1})
    except AuthError as e:
        emit({"ok": False, "reason": reason_of(e)})
        return 2
    except CliError as e:
        emit({"ok": False, "reason": reason_of(e)})
        return 1
    emit({"ok": True})
    return 0


def register(subparsers) -> None:
    auth = subparsers.add_parser("auth", help="store the API token and check it")
    sub = auth.add_subparsers(dest="auth_command", parser_class=type(auth))
    setup = sub.add_parser("setup", help="prompt for the token and save it to the config file")
    setup.set_defaults(handler=_setup_handler)
    check = sub.add_parser("check", help="probe the token (exit 0 ok, 2 auth failure, 1 other)")
    check.set_defaults(handler=_check_handler)
