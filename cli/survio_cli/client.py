"""HTTP client for the Survio REST API: auth, write gate, dry-run, retries, paging."""
import http.client
import json
import math
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Iterator, Optional, Tuple
from urllib.parse import urlencode

from .config import Config
from .errors import ApiError, AuthError, WriteBlocked

TIMEOUT = 30
MAX_ATTEMPTS = 3
BACKOFF = (1, 2)
MAX_RETRY_AFTER = 60

# stderr may land in an agent's context: these name no variable and no config path, so they
# never invite the agent to switch writes on or to go looking for the token itself
WRITES_OFF = ("Writes are off. Only the user can turn them on in the survio CLI config. "
              "Use --dry-run to preview the request.")
NO_TOKEN = ("No Survio API token configured. "
            "The user should run `survio auth setup` in their own terminal.")


class _NetworkError(ApiError):
    """The request failed before any response arrived (safe to replay only if it was a read)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: urllib would otherwise forward Authorization to the new location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _query_string(query: Optional[dict]) -> str:
    pairs = []
    for key, value in (query or {}).items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            if v is None:
                continue
            if isinstance(v, bool):
                v = "true" if v else "false"
            pairs.append((key, v))
    return urlencode(pairs)


class Client:
    def __init__(self, config: Config, sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self._sleep = sleep

    def _mask(self, text: str) -> str:
        token = self.config.token
        return text.replace(token, "***") if token else text

    def _url(self, path: str, query: Optional[dict]) -> str:
        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/")
        qs = _query_string(query)
        return url + ("?" + qs if qs else "")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[dict] = None,
        body: Optional[Any] = None,
        write: bool = False,
        dry_run: bool = False,
    ) -> Any:
        method = method.upper()
        url = self._url(path, query)
        if dry_run:
            return {
                "dry_run": True,
                "method": method,
                "url": url,
                "headers": {"Authorization": "Bearer ***", "Content-Type": "application/json"},
                "body": body,
            }
        if write and not self.config.allow_writes:
            raise WriteBlocked(WRITES_OFF)
        if not self.config.token:
            raise AuthError(NO_TOKEN)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": "Bearer " + self.config.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                status, raw, resp_headers = self._send(method, url, data, headers)
            except _NetworkError:
                # a write may have been applied before the connection broke: never replay it
                if write or attempt == MAX_ATTEMPTS:
                    raise
                self._sleep(self._delay(None, attempt))
                continue
            # a 5xx on a write may mean the server already acted: never replay it
            retryable = status == 429 or (status >= 500 and not write)
            if retryable and attempt < MAX_ATTEMPTS:
                self._sleep(self._delay(resp_headers.get("Retry-After"), attempt))
                continue
            break
        if status in (401, 403):
            raise AuthError("The Survio API rejected the token (HTTP %d). "
                            "The user should check it with `survio auth setup`." % status, status=status)
        if status >= 300:  # 3xx included: redirects are never followed
            raise ApiError(self._error_message(status, raw), status=status)
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            raise ApiError(self._error_message(status, raw), status=status)

    def _send(self, method, url, data, headers):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read().decode("utf-8", "replace"), resp.headers
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", "replace")
            except (http.client.HTTPException, OSError) as read_error:
                # keep the status so the retry rules still apply (a GET 5xx/429 is replayed)
                raw = "(response body unreadable: %s)" % type(read_error).__name__
            return e.code, raw, e.headers
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            raise _NetworkError(self._mask("Request failed: %s" % e))

    @staticmethod
    def _delay(retry_after: Optional[str], attempt: int) -> float:
        if retry_after:
            try:
                seconds = float(retry_after)
            except (ValueError, OverflowError):
                seconds = math.nan
            if not math.isnan(seconds):
                return int(max(0, min(MAX_RETRY_AFTER, seconds)))
        return BACKOFF[attempt - 1]

    def _error_message(self, status: int, raw: str) -> str:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and (parsed.get("code") or parsed.get("message")):
            detail = ": ".join(str(parsed[k]) for k in ("code", "message") if parsed.get(k))
        else:
            detail = raw
        return self._mask("HTTP %d %s" % (status, detail)).strip()[:200]

    def paginate_pages(
        self,
        path: str,
        *,
        query: Optional[dict] = None,
        page_limit: int = 10,
        start_page: int = 1,
    ) -> Iterator[Tuple[int, list]]:
        """GET `path` with page=N, yielding (N, items) until an empty page (or a 404 after the
        first page). page_limit 0 means unlimited."""
        page = start_page
        fetched = 0
        while True:
            q = dict(query or {})
            q["page"] = page
            try:
                items = self.request("GET", path, query=q)
            except ApiError as e:
                if e.status == 404 and page > start_page:
                    return
                raise
            if not isinstance(items, list):
                raise ApiError("expected a JSON array")
            if not items:
                return
            yield page, items
            fetched += 1
            if page_limit and fetched >= page_limit:
                return
            page += 1
