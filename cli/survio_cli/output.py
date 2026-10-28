import contextlib
import errno
import json
import os
import stat
import sys
import tempfile
from typing import Any, Iterator, Optional

from .errors import CliError


@contextlib.contextmanager
def atomic_writer(path: str) -> Iterator[Any]:
    """Text file handle for `path`; the file appears (os.replace) only when the block succeeds.

    The temp file lives in the target directory so the replace is atomic; on any failure it is
    removed and an existing `path` is left untouched. A symlink (even a dangling one) stays a link:
    the file it points at is written.
    """
    mode = None
    try:
        st = os.stat(path)  # follows symlinks
    except OSError as e:
        st = None
        if e.errno == errno.ELOOP:
            raise CliError("cannot write %s: symlink loop" % path)
        if os.path.islink(path):  # dangling link: create the file it points at, keep the link
            resolved = os.path.realpath(path)
            if os.path.islink(resolved):  # realpath gave up: the links never reach a file
                raise CliError("cannot write %s: symlink loop" % path)
            path = resolved
    if st is not None:
        if not stat.S_ISREG(st.st_mode):  # /dev/stdout, a fifo...: cannot be replaced
            with open(path, "w", encoding="utf-8") as f:
                yield f
            return
        mode = stat.S_IMODE(st.st_mode)
        path = os.path.realpath(path)  # replace the file a symlink points at, not the link
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".survio-", suffix=".tmp", dir=directory)  # mode 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yield f
        if mode is not None:
            os.chmod(tmp, mode)  # an existing file keeps its permissions
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)  # our own temp file
        except OSError:
            pass
        raise


def emit(data: Any, out: Optional[str] = None, stream=None) -> None:
    """Print JSON (indented on a TTY, compact otherwise) or write it to `out`."""
    stream = sys.stdout if stream is None else stream
    if out:
        with atomic_writer(out) as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        return
    if stream.isatty():
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    stream.write(text + "\n")


def emit_line(data: Any, stream=None) -> None:
    """One compact JSON line (NDJSON)."""
    stream = sys.stdout if stream is None else stream
    stream.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def emit_text(line: str, stream=None) -> None:
    """One plain-text line (listings that are not JSON)."""
    stream = sys.stdout if stream is None else stream
    stream.write(line + "\n")
