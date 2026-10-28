import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional

DEFAULT_BASE_URL = "https://api2.survio.com/v2"


@dataclass
class Config:
    token: Optional[str] = None
    allow_writes: bool = False
    base_url: str = DEFAULT_BASE_URL


def _default_path(environ: Mapping[str, str]) -> Path:
    """$XDG_CONFIG_HOME/survio-cli/<env file>, else ~/.config/survio-cli/<env file>."""
    xdg = environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "survio-cli" / ".env"


config_path = _default_path


def parse_env_file(text: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines: `export` prefix, quotes, comments and CRLF are handled."""
    result = {}  # type: Dict[str, str]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export"):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        result[key] = _parse_value(value.strip())
    return result


def _parse_value(value: str) -> str:
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
    # unquoted: a '#' preceded by whitespace starts a comment
    for i, ch in enumerate(value):
        if ch == "#" and i > 0 and value[i - 1] in " \t":
            return value[:i].rstrip()
    return value


def load_config(
    environ: Mapping[str, str] = os.environ, config_path: Optional[Path] = None
) -> Config:
    """Process environment first, then the config file; never the current directory."""
    path = config_path if config_path is not None else _default_path(environ)
    file_vars = {}  # type: Dict[str, str]
    try:
        file_vars = parse_env_file(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        pass

    def get(name: str) -> Optional[str]:
        # an empty or blank env var does not hide the file's value
        value = (environ.get(name) or "").strip()
        if not value:
            value = (file_vars.get(name) or "").strip()
        return value or None

    return Config(
        token=get("SURVIO_API_TOKEN"),
        allow_writes=get("SURVIO_ALLOW_WRITES") == "1",
        base_url=get("SURVIO_API_URL") or DEFAULT_BASE_URL,
    )
