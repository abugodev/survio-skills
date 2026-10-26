# Survio skills

Agent skills that read your Survio survey results and turn them into a report people can
act on. The skill works like a careful survey analyst: **numbers that are right and
reproducible**, and **never exposing an individual respondent**.

The skills use the open [Agent Skills](https://agentskills.io) format: a `SKILL.md` folder
with a dependency-free Python script. They run in any harness that loads skills:
- **Claude Code** and **Codex**, as a plugin;
- **Gemini CLI**, as an extension;
- **pi**, as a package;
- any other agent, by copying the `skills/` folder.

- [The problem](#the-problem)
- [How it works](#how-it-works)
- [Install](#install)
  - [Claude Code](#claude-code)
  - [Codex](#codex)
  - [Gemini CLI](#gemini-cli)
  - [pi](#pi)
  - [Other harnesses](#other-harnesses)
- [The skills](#the-skills)
- [Privacy](#privacy)
- [Repository layout](#repository-layout)
- [Survio documentation](#survio-documentation)
- [Licence](#licence)

## The problem

Ask an AI assistant "what does this survey say?" and you usually get a fluent answer.
Some of it may be wrong, and some of it may be unsafe:

- **wrong numbers:** percentages of the wrong base, statistics estimated by eye, a
  10-point NPS swing called significant when it is noise, a partial download analysed as
  if it were complete;
- **exposed people:** a mean for a team of three, a crosstab cell of two, a quote that
  names the only person in a role. In employee surveys this can reveal who said what.

This skill makes the agent compute every number with a bundled script, choose methods by
the shape of the data, and apply anonymity rules to every survey, not only HR ones.

## How it works

```
Survio MCP (read tools)             local script                        report
──────────────────────────    ──────────────────────────────    ─────────────────────────────
survio_list_surveys       →   survey_data/<id>/page_N.tsv   →   report.md
survio_list_survey_responses  analyze.py profile / quality        key findings · sample & quality
  (page by page until          nps · drivers · segments           segment differences · themes
   hasMore is false)           waves · vw · text · moe            caveats
                               checkquote · checkreport  (lint)
```

1. **Find the survey** and **pull every response page** into a compact TSV, then check the
   row count against the totals the MCP reports.
2. **Profile** the data and **check quality**: straight-liners, duplicates, gibberish,
   non-answers.
3. **Pick methods** from a decision table: NPS/eNPS with confidence intervals, key drivers,
   segment tests with multiple-comparison correction, open-text theme coding, wave
   comparison, Van Westendorp price ranges, margin of error for small samples.
4. **Write the report** with a fixed structure in the user's language, then **lint it**:
   every quote must be verbatim and safe, and the prose must not leak small-group numbers
   or identifying details.

The script (`analyze.py`) uses only the Python 3 standard library. Nothing is installed and
nothing leaves your machine except the MCP calls your assistant makes.

## Install

Every harness needs:
- **The Survio MCP server** (`https://ai.survio.com/mcp`), connected and signed in to your
  Survio account. Survio MCP is available on PRO Business and higher. Sign-in uses OAuth,
  so there is no API key.
- **Python 3.9+**, for the bundled script.

Installation differs by harness. If you use more than one, install separately for each.

### Claude Code

1. Connect the Survio MCP server (see
   [How to connect Survio to Claude Code](https://www.survio.com/en/help/articles/17087490-how-to-connect-survio-to-claude-code)):

   ```bash
   claude mcp add survio --scope user --transport http https://ai.survio.com/mcp
   ```

   Then run `/mcp` in Claude Code, select **survio** and choose **Authenticate**.

2. Install the plugin inside Claude Code:

   ```
   /plugin marketplace add abugodev/survio-skills
   /plugin install survio-insights@survio-skills
   ```

In the Claude desktop app, connect Survio as described in
[How to connect Survio to Claude Desktop](https://www.survio.com/en/help/articles/17087463-how-to-connect-survio-to-claude-desktop).

### Codex

1. Connect the Survio MCP server and sign in (see
   [How to connect Survio to Codex and the ChatGPT desktop app](https://www.survio.com/en/help/articles/17087517-how-to-connect-survio-to-codex-and-the-chatgpt-desktop-app)):

   ```bash
   codex mcp add survio --url https://ai.survio.com/mcp
   codex mcp login survio
   ```

2. Add this repository as a plugin marketplace and install the plugin:

   ```bash
   codex plugin marketplace add abugodev/survio-skills
   codex plugin add survio-insights@survio-skills
   ```

   In Codex in the ChatGPT desktop app, the added marketplace also appears as a source in
   the Plugins Directory.

### Gemini CLI

1. Connect the Survio MCP server as a remote HTTP server with OAuth sign-in (see
   [How to connect Survio to any other AI tool](https://www.survio.com/en/help/articles/17087538-how-to-connect-survio-to-any-other-ai-tool)).
2. Install the extension. Gemini CLI discovers the bundled `skills/` automatically:

   ```bash
   gemini extensions install https://github.com/abugodev/survio-skills
   ```

   Update later with `gemini extensions update survio-insights`.

### pi

Install the skills as a [pi](https://pi.dev) package and connect the Survio MCP server:

```bash
pi install git:github.com/abugodev/survio-skills
pi mcp add survio --url https://ai.survio.com/mcp
pi mcp login survio
```

### Other harnesses

The skills are plain [Agent Skills](https://agentskills.io) folders. For any agent that
loads skills from a directory, copy (or symlink) the folders in `skills/` there:

- `~/.agents/skills/`: read by Codex, pi and Gemini CLI;
- `~/.claude/skills/`: Claude Code personal skills.

Then connect the Survio MCP server in that agent (see
[How to connect Survio to any other AI tool](https://www.survio.com/en/help/articles/17087538-how-to-connect-survio-to-any-other-ai-tool)).

```bash
git clone https://github.com/abugodev/survio-skills
mkdir -p ~/.agents/skills && cp -R survio-skills/skills/* ~/.agents/skills/
```

If your agent has no skill loader, point it at `AGENTS.md` and
`skills/survey-analyst/SKILL.md`: the instructions are self-contained.

**Using the skills:** ask in plain words, in any language, for example:
- *"what does the customer satisfaction survey say?"*;
- *"compare eNPS between teams in the autumn pulse"*;
- *"shrň mi výsledky průzkumu"*.

In Codex you can also mention the skill with `$`, e.g. `$survey-analyst`.

## The skills

All examples below are fictional.

### survey-analyst

**Purpose:** analyze the results of a Survio survey the way a senior survey analyst would,
and write a report that is reproducible and safe to share.

**Use when:** someone asks what a survey says, wants results, insights or a summary,
NPS/eNPS, "what do people complain about", themes from comments, a comparison between
teams, segments or waves, pricing research results, or a data-quality check.

**Not for:** creating or editing surveys, sending invitations or reminders, or exporting
responses without analysis.

**Input:** a Survio survey (or two waves of the same questionnaire), read through the
Survio MCP.

**Output:** `report.md` in the user's language, with five sections: key findings, sample
and data quality, segment differences, themes, caveats. The working data stays in
`survey_data/<surveyId>/`.

What `analyze.py` does:

| Command | What |
|---|---|
| `profile` | n, question keys, types, answer rates, segment sizes, groups with n<5 |
| `quality` | straight-liners, duplicates, gibberish, non-answers, completion-time outliers |
| `nps` | NPS / eNPS with a 95% confidence interval, optionally per segment |
| `summary`, `compare`, `segments` | ratings per segment; pairwise and every-group-vs-rest tests with Holm correction |
| `drivers` | key drivers: Spearman correlation and promoter-vs-detractor gap per attribute |
| `waves` | the same questionnaire run twice: shift and significance |
| `vw` | Van Westendorp price range |
| `text` | open answers for theme coding |
| `moe` | margin of error |
| `checkquote` | is a quote verbatim, and is it safe to quote? |
| `checkreport` | lint a finished report for small-group numbers and identifying details |

```markdown
## Key findings
- NPS is +18 (95% CI +9 to +27, n=212), unchanged from wave 1 (+15, n=198; no reliable
  difference, p=0.61).
- Delivery speed is the strongest driver: promoters rate it 1.4 points higher than
  detractors.
- Support scores lower for customers on the Basic plan (3.6 vs 4.1 of 5, n=88 vs 124,
  significant after Holm correction).

## Sample & data quality
212 responses, 3–16 March. 6 straight-liners excluded (results with and without them
match). Margin of error for NPS: ±9 points.
```

## Privacy

Anonymity rules apply to every survey, not only HR ones:

1. **No metric for a group with fewer than 5 respondents.** No mean, NPS, percentage or
   count, including crosstab cells. `analyze.py` suppresses them.
2. **No back-calculation.** When a group is hidden, the script applies secondary
   suppression or merges small groups into "Other", so the hidden value cannot be
   subtracted from the total.
3. **No identifying quotes.** Names, emails, phone numbers, unique roles or
   tenure-and-role combinations are paraphrased, never quoted. `checkquote` must approve
   every quote.
4. **Report lint.** `checkreport` catches what slips into prose: small-group sizes,
   contact details, text lifted from identifying answers, and identifying descriptions
   restated in the agent's own words.

The working data is a local folder; the plugin sends nothing to third parties. As with any
MCP connector, the responses your assistant fetches pass through it as conversation
context. The skill never sends survey invitations unless you ask for exactly that.
Automated checks can miss things, so review a report before you share it.

## Repository layout

| Path | What |
|---|---|
| `skills/` | The skills (`SKILL.md` + `scripts/` + `references/`) |
| `AGENTS.md` | Instructions for agents using or maintaining the skills |
| `.claude-plugin/` | Claude Code plugin + marketplace manifests |
| `.codex-plugin/`, `.agents/plugins/marketplace.json` | Codex plugin manifest + marketplace |
| `gemini-extension.json` | Gemini CLI extension manifest |
| `package.json` | pi package manifest |

## Survio documentation

- [Survio MCP: work with your survey results through your AI assistant](https://www.survio.com/en/help/articles/17087442-survio-mcp-work-with-your-survey-results-through-your-ai-assistant): what the MCP server can do
- [Which Survio integration do I need? MCP, API, webhooks or Zapier](https://www.survio.com/en/help/articles/17087455-which-survio-integration-do-i-need-mcp-api-webhooks-or-zapier)
- [How to connect Survio to Claude Desktop](https://www.survio.com/en/help/articles/17087463-how-to-connect-survio-to-claude-desktop)
- [How to connect Survio to Claude Code](https://www.survio.com/en/help/articles/17087490-how-to-connect-survio-to-claude-code)
- [How to connect Survio to Codex and the ChatGPT desktop app](https://www.survio.com/en/help/articles/17087517-how-to-connect-survio-to-codex-and-the-chatgpt-desktop-app)
- [How to connect Survio to Cursor](https://www.survio.com/en/help/articles/17087504-how-to-connect-survio-to-cursor)
- [How to connect Survio to any other AI tool](https://www.survio.com/en/help/articles/17087538-how-to-connect-survio-to-any-other-ai-tool)
- [Analyze your survey responses with AI](https://www.survio.com/en/help/articles/17242053-analyze-your-survey-responses-with-ai-how-to-ask-what-it-can-do-and-what-to-avoid): how to ask, what it can do and what to avoid

## Licence

[MIT](LICENSE) © 2026 Abugo
