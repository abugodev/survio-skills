from ..errors import UsageError
from ..ops import Op, Param


def _read_emails_file(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise UsageError("cannot read %s: %s" % (path, e.strerror or e))
    return [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]


def _build_batch_body(args) -> dict:
    emails = [e.strip() for e in (getattr(args, "b_emails", None) or []) if e.strip()]
    path = getattr(args, "x_emails_file", None)
    if path:
        emails += _read_emails_file(path)
    if not emails:  # fall back to the addresses given with --json
        emails = getattr(args, "json_obj", {}).get("emails")
    if not isinstance(emails, list) or not emails:
        raise UsageError("no email addresses: give --email (repeatable), --emails-file "
                         "or --json with a non-empty \"emails\" list")
    return {"emails": emails}


OPS = [
    Op("invitations", "send", "POST", "/api/survey/{id}/send-invitation", True, "api_send_email",
       "email one invitation to a survey (needs writes enabled; --dry-run previews)",
       path_params=["id"], path_metavars={"id": "SURVEY_ID"},
       body=[Param("email", "--email", required=True, help="recipient address, <email>")]),
    Op("invitations", "send-batch", "POST", "/api/survey/{id}/send-invitation/batch", True,
       "api_batch_send_email_batch",
       "email invitations to several recipients (needs writes enabled; --dry-run previews)",
       path_params=["id"], path_metavars={"id": "SURVEY_ID"},
       body=[Param("emails", "--email", repeat=True, required=True,
                   help="recipient address, <email> (repeatable; or use --emails-file)")],
       extra=[Param("emails_file", "--emails-file",
                    help="file with one address per line; blank lines and # comments ignored")],
       build_body=_build_batch_body),
]
