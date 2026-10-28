# survio CLI

`survio` is a command-line client for the Survio REST API
(`https://api2.survio.com/v2`). It lists surveys, reads and filters responses, downloads a
survey's responses for analysis and sends invitations. It prints JSON and needs only
Python 3.9 or later — no dependencies.

It is part of [survio-skills](../README.md) and optional: the skills use the Survio MCP
without it. With it, `survio responses +fetch` downloads responses straight to disk, so
the answers don't pass through your AI assistant and fetching costs no model tokens.

## Install

```bash
uv tool install "git+https://github.com/abugodev/survio-skills#subdirectory=cli"
# or
pipx install "git+https://github.com/abugodev/survio-skills#subdirectory=cli"
```

From a clone, without installing: `PYTHONPATH=cli python3 -m survio_cli --help`.

## Set up a token

1. Ask Survio support (support@survio.com) for an API token; Survio has no
   self-service token page.
2. Store it. Run this in your own terminal; it asks for the token without showing it and
   never takes it as an argument:

   ```bash
   survio auth setup
   survio auth check
   ```

The token is kept in `~/.config/survio-cli/.env` (or `$XDG_CONFIG_HOME/survio-cli/.env`)
with mode `0600`. Environment variables override the file; the names are listed in
[.env.example](../.env.example).

**Every token has full access to your Survio account.** Write commands (invitations) are
blocked (exit code 4) unless you add `SURVIO_ALLOW_WRITES=1` to the config file, and every
write command accepts `--dry-run` to show the request without sending it. Keep writes off
unless you need them: invitations reach real people and cannot be undone.

## Use

```bash
survio schema                                        # every command
survio surveys list --page-all
survio responses list 123456 --lang en --submitted-after 2026-10-01 --page-all
survio responses +fetch 123456 --ws ./survey_data/123456
survio invitations send 123456 --email <email> --dry-run   # writes: preview first
```

Commands follow `survio <resource> <method>` (surveys, responses, invitations), plus
`auth` and `schema`. `--help` on any command shows its options; `survio schema <resource>
<method>` shows an API command's endpoint, parameters and whether it reads or writes
(`survio schema` marks the helpers and local commands, which have no single endpoint).

`responses list` output contains respondents' emails and answers. `responses +fetch`
writes `page_<N>.tsv` files without emails, URL parameters or EMAIL questions, plus a
manifest in `.survio/manifest.json`, and prints only counts. It never deletes data: files
from an earlier run that it did not rewrite are moved to `previous/`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | API or network error |
| 2 | Token missing or rejected |
| 3 | Bad arguments |
| 4 | Write blocked (writes are off) |

The full command reference, for people and AI assistants, is in
[skills/survio-cli/SKILL.md](../skills/survio-cli/SKILL.md).
