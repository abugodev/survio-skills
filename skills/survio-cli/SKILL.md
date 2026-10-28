---
name: survio-cli
description: Use the `survio` command-line tool for the Survio REST API — setup, the route check, every command, response filter flags, `+fetch`, the write switch. Use when the user mentions the "Survio API" or the "survio CLI", wants to "filter Survio responses by source/language/date", wants to "download Survio responses" to disk, wants to "send a Survio invitation from the command line", or when another Survio skill picks the CLI route.
---

# survio CLI

`survio` is a command-line client for the Survio REST API
(`https://api2.survio.com/v2`). `responses +fetch` writes a survey's responses straight
from the API to disk, so they do not pass through the conversation; other commands print
the API's JSON to stdout, or write it to a file with `--out FILE`. It is optional: without
it the other skills use the Survio MCP.

## Rules

- **Never read, print or edit the config file** (`~/.config/survio-cli/.env`, or
  `$XDG_CONFIG_HOME/survio-cli/.env`). Only the user edits it.
- **Never set `SURVIO_ALLOW_WRITES` or `SURVIO_API_TOKEN` inline**, export them, or pass
  them to a command in any other way. Turning writes on is the user's decision.
- Never print, echo or log the token. The CLI never shows it; keep it that way.
- **Every token has full access to the account.** Nothing suggests Survio issues scoped or
  read-only tokens. The write switch guards against accidents, not against a deliberate
  misuse.
- **The output of `responses list` contains respondents' emails and answers.** Don't paste
  it into results, reports or chat. For analysis use `responses +fetch`, which leaves
  emails out.
- **Invitations reach real people and cannot be undone.** Send them only when the user
  asks for exactly that.

## Install and set up (the user does this once)

```bash
uv tool install "git+https://github.com/abugodev/survio-skills#subdirectory=cli"
# or
pipx install "git+https://github.com/abugodev/survio-skills#subdirectory=cli"

survio auth setup
```

Survio has no self-service token page: the user asks Survio support
(support@survio.com) for an API token. `auth setup` asks for the token on the terminal
and stores it in the config file with mode `0600`. It never takes the token as an argument
and refuses to run without a terminal. The user runs it in their own terminal, not through
the agent.

Variables (process environment first, then the config file; never the current directory):

| Variable | Meaning |
|---|---|
| `SURVIO_API_TOKEN` | API token. Required for every command except `schema`, `--help`, `auth setup` and write commands run with `--dry-run`. |
| `SURVIO_ALLOW_WRITES` | `1` turns write commands (invitations) on. Anything else, or missing, means off. |
| `SURVIO_ROUTE` | `auto` (default), `cli` or `mcp`. Read by the skills from the environment, not by the CLI. |
| `SURVIO_API_URL` | Override the base URL (for tests). |

## The route check

Skills that can use either route decide like this:

1. `SURVIO_ROUTE=mcp` → use the MCP.
2. `SURVIO_ROUTE=cli` → use the CLI; if `survio auth check` fails, stop and tell the user.
3. `auto` or unset → run `survio auth check`:
   - exit 0 → CLI;
   - exit 2, or `survio` not found → MCP;
   - exit 1 → report the error to the user, then use the MCP.
4. Any other value (`mcp` and `cli` match in any case) → treated as `auto`.

`auth check` makes one cheap read and prints only `{"ok": true}` or
`{"ok": false, "reason": "…"}`.

On the CLI route, start the analysis only when the workspace's `.survio/manifest.json` has
`"complete": true`.

## Commands

Shape: `survio <resource> <command> [SURVEY_ID] [flags]`. Ids are positional
(`survio responses list 123456`). Output is the API's JSON on stdout; `--out FILE` writes
it to a file. `survio schema` lists every command (helpers such as `responses +fetch` and
`auth check`, and the local `auth setup`, are marked); `survio schema <resource> <command>`
prints an API command's endpoint, read/write class and fields (offline). `--help` works on
every command.

| Command | What | Class |
|---|---|---|
| `surveys list` | your surveys | read |
| `responses list SURVEY_ID` | responses of a survey, with filters | read |
| `responses +fetch SURVEY_ID --ws DIR` | every response into a `survey-analyst` workspace | read |
| `invitations send SURVEY_ID --email <email>` | email one invitation | write |
| `invitations send-batch SURVEY_ID (--email <email> … \| --emails-file FILE)` | email several invitations | write |
| `auth setup` | store the token (the user, in their own terminal) | — |
| `auth check` | probe the token | — |
| `schema [RESOURCE COMMAND]` | describe commands, offline | — |

Paging (`surveys list`, `responses list`):

| Flag | Meaning |
|---|---|
| `--page N` | page to fetch (default 1); with `--page-all`, the first page |
| `--page-all` | follow the pages; one JSON line (an array) per page |
| `--page-limit N` | most pages with `--page-all`; default 10, `0` = no limit |
| `--query KEY=VALUE` | extra query parameter passed through as given (repeatable; explicit flags win) |

`--page-all` stops after `--page-limit` pages (default 10) and gives no sign that more
pages were left. For a complete download of a survey's responses use `responses +fetch`
and check that its manifest says `"complete": true`.

### Response filters

`responses list` and `responses +fetch` take the same filters:

| Flag | Meaning |
|---|---|
| `--source NAME` | collector source (repeatable): `FB_WALL`, `EMAIL`, `TWITTER`, `WEB_LINK`, `IFRAME`, `DIRECT`, `CINT`, `POPUP`, `LINKEDIN`, `GPLUS`, `VKONTAKTE`, `QR_CODE`, `POPOVER`, `WHATSAPP`, `SOC_NETWORK`, `IN_APP` |
| `--lang CODE` | language code, e.g. `en` (repeatable) |
| `--submitted-after`, `--submitted-before` | submitted at or after / at or before this date or date-time |
| `--submitted-strictly-after`, `--submitted-strictly-before` | the same, excluding the boundary |
| `--completion-time-min`, `--completion-time-max` | completion time in seconds, at least / at most |
| `--completion-time-above`, `--completion-time-below`, `--completion-time-exact` | completion time in seconds, more than / less than / exactly |
| `--order asc\|desc` | sort by submission time |
| `--query KEY=VALUE` | any other query parameter of the API, passed through |

Example:
`survio responses list 123456 --lang en --source WEB_LINK --submitted-after 2026-10-01 --page-all`.

Verified against the live API:

- `responses list` returns 30 responses per page; past the last page it returns `[]`.
- A date (`2026-10-01`) means that day's 00:00, so `--submitted-before 2026-10-01`
  excludes that day. A date-time's offset (`Z`, `+01:00`) is ignored: the time is read in
  the account's time zone, the one `submitted` is shown in. Bounds are inclusive.
- Completion-time filters match almost nothing: most responses have no completion time.
  Don't use them to find speeders.

### +fetch

```bash
survio responses +fetch SURVEY_ID --ws DIR [filters]
```

Does the data step of `survey-analyst` in one command: writes `page_<N>.tsv` (one per API
page, the TSV `analyze.py` reads) into `DIR`, and the manifest into
`DIR/.survio/manifest.json` — not into `DIR` itself, because `analyze.py` reads every
top-level `.json` there. Default order: submission time ascending. It takes no `--page`.

- Respondents' emails, URL parameters and EMAIL-type questions are left out.
- A question label that repeats an earlier one is renamed `X (2)`, `X (3)`, …, with a
  warning on stderr naming the question ids.
- `.tsv` and `.json` files already at the top of `DIR` that this run did not write are
  moved to `DIR/previous/`, never deleted.
- It prints counts only: `{"responses": N, "pages": N}`.
- `manifest.json` has `"complete": false` while the run is going and after an aborted run,
  `true` when it finished. Its `counts` are the completeness check.
- Columns follow the questionnaire order (the order answers come in), not question ids.
  Question types beyond NPS, rating, number, single choice, matrix and text:

  | Type | Column(s) | Cell |
  |---|---|---|
  | single choice, dropdown, image single choice | `[CHOICE] q` | label; "Other" → `Other: <text>` |
  | multiple choice, image multiple choice | `[MULTI] q` | labels joined ` \| `, then `Other: <text>` |
  | date, place | `[TEXT] q` | as given |
  | smiley rating (EMOJI) | `[RATING] q` | 1 = first smiley |
  | sorting | `[MATRIX] q :: <item>` | rank, 1 = top |
  | semantic differential | `[MATRIX] q :: <left> – <right>` | the number (-2…2) |
  | divide points | `[MATRIX] q :: <item>` | the points |
  | multiple-choice matrix | `[MULTI] q :: <row>` | column labels joined ` \| ` |
  | text matrix | `[TEXT] q :: <row> :: <column>` | the text |
  | email | left out | — |

- Checked against the MCP route: same responses, same `submitted` values, same column order
  and identical `analyze.py profile` output for NPS, rating, number, single-choice,
  single-choice matrix and text questions. The other types' answer shapes were checked on
  a live survey, except place and image multiple choice (mapped, not yet seen live). Types
  listed in the manifest's `unmapped_types` are written as TEXT and need a look before
  analysis.

### Invitations

`invitations send-batch` takes `--email <email>` (repeatable) or `--emails-file FILE`: a
text file with one address per line; blank lines and lines starting with `#` are ignored.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | API or network error (after retries); short message on stderr |
| 2 | Token missing, invalid or rejected (401/403) |
| 3 | Bad arguments |
| 4 | Write blocked (`SURVIO_ALLOW_WRITES` is not `1`) |

Reads are retried after a 429, a 5xx or a network error (3 attempts in all). Writes are
retried only after a 429 and never after a 5xx or a network error, because the
invitation may already have gone out; check with the user before running one again.

## Writes

The invitation commands are the only writes. They work only when the user has set
`SURVIO_ALLOW_WRITES=1` in the config file; otherwise they exit 4 and send nothing. Every
write accepts `--dry-run`, which prints the request it would send (token shown as `***`)
and sends nothing — it works while writes are off. Run `--dry-run` first and show it to
the user. Send invitations only when the user asked for exactly that, to exactly those
addresses. On exit 4, tell the user writes are off; don't turn them on yourself. If the
token is missing, the user runs `survio auth setup` in their own terminal.
