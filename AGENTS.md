# survio-skills — instructions for agents

Agent skills that analyze Survio survey results (read through the Survio MCP server) and
write reports with reproducible numbers and anonymity guardrails always on. The skills
follow the open [Agent Skills](https://agentskills.io) format and work in any harness that
loads `SKILL.md` folders: Claude Code, Codex, pi, Gemini CLI and others.

## Layout

| Path | What |
|---|---|
| `skills/<skill>/SKILL.md` | The skills: YAML front matter (`name`, `description`), then instructions. Optional `scripts/` and `references/`. |
| `skills/survey-analyst/` | Survey analysis: workflow, decision table, report contract, guardrails. `scripts/analyze.py` computes every number; `references/` hold the method notes. |
| `skills/survio-cli/` | How to use the optional `survio` CLI (REST API): setup, route check, commands, filters, write switch. |
| `cli/` | The `survio` CLI itself (Python package, standard library only). |
| `.claude-plugin/` | Claude Code plugin and marketplace manifests. |
| `.codex-plugin/`, `.agents/plugins/marketplace.json` | Codex plugin manifest and marketplace. |
| `gemini-extension.json` | Gemini CLI extension manifest. |
| `package.json` | pi package manifest (`pi.skills`). |

## Install the CLI (optional)

Without it, the skills read Survio through the MCP. With it, responses can be fetched
straight to disk over the REST API, so answers do not pass through the model. The user
installs it and stores an API token (Survio support issues tokens):

```bash
uv tool install "git+https://github.com/abugodev/survio-skills#subdirectory=cli"
survio auth setup
```

`pipx install` with the same URL works too. The route is chosen by `SURVIO_ROUTE`
(`auto`, `cli`, `mcp`); see `skills/survio-cli/SKILL.md`. Never read, print or edit the
CLI's config file, and never set `SURVIO_API_TOKEN` or `SURVIO_ALLOW_WRITES` yourself.
Every token has full access to the account.

## Using the skills

1. `survey-analyst` pulls all responses of a survey page by page into
   `survey_data/<surveyId>/page_<N>.tsv` in the working directory, then runs
   `scripts/analyze.py` on that folder.
2. The script is Python 3, standard library only. Run it with `python3`. Paths in a
   `SKILL.md` are relative to that skill's folder.
3. Get numbers from `analyze.py` instead of computing them yourself. Check quotes with
   `analyze.py checkquote` and lint the finished report with `analyze.py checkreport`.

## Harness notes

- **Tool names.** The skills name the Survio MCP's own tools (`survio_list_surveys`,
  `survio_list_survey_responses`). Harnesses show them with their own prefix, e.g.
  `mcp__survio__survio_list_surveys` in Claude Code. Use whatever name your harness
  exposes for the same tool.
- **Read-only.** Only the two read tools above are needed. Never call
  `survio_send_invitation` or `survio_send_invitation_batch` unless the user asks for
  exactly that: invitations reach real people and cannot be undone.
- **Pagination.** Responses come in pages; keep fetching until `hasMore` is false and check
  that the row count matches before analysing.
- **No skill tool?** Read the relevant `skills/<skill>/SKILL.md` and follow it.

## Personal data

Survey answers can identify respondents. Never report a metric for a group with fewer than
5 respondents, never publish numbers that let a hidden group be back-calculated, and never
quote an answer that could identify a person — `analyze.py` enforces these rules and
`checkquote` / `checkreport` must pass. Never publish or send anything (email, Slack,
documents, Survio invitations) unless the user asks and names the destination.

## Maintaining the skills

- Keep skill text harness-neutral. Describe actions ("fetch", "read", "write a file"),
  not one harness's tool names. When a step really differs per harness, say so
  explicitly for each harness.
- Keep scripts and `cli/` dependency-free (Python 3 standard library; `cli/` stays
  Python 3.9-compatible).
- Examples in skills and code comments must be fictional and neutral. Never paste real
  respondent data, real company names or survey answers.
- When you change the plugin version, bump it in every manifest:
  `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  `.codex-plugin/plugin.json`, `gemini-extension.json`, `package.json`,
  `cli/pyproject.toml` and `__version__` in `cli/survio_cli/__init__.py`.
