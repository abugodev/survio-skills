from typing import Optional


class CliError(Exception):
    """Base error; main() prints it and exits with exit_code."""

    exit_code = 1


class ApiError(CliError):
    exit_code = 1

    def __init__(self, message: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.status = status  # HTTP status code; None when no response arrived


class AuthError(CliError):
    exit_code = 2

    def __init__(self, message: str = "", status: Optional[int] = None):
        super().__init__(message)
        self.status = status  # 401/403; None when no token was configured


class UsageError(CliError):
    exit_code = 3


class WriteBlocked(CliError):
    exit_code = 4


def reason_of(exc: CliError) -> str:
    """Short reason free of tokens and personal data: the HTTP status code, "network" (no
    response), "bad response" (2xx that was not JSON), "no token" or "error"."""
    status = getattr(exc, "status", None)
    if status is None:
        if isinstance(exc, AuthError):
            return "no token"
        return "network" if isinstance(exc, ApiError) else "error"
    return "bad response" if 200 <= status < 300 else str(status)
