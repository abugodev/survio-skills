---
name: survey-analyst
description: Analyze Survio survey results like a senior survey analyst — pull responses via the Survio MCP, profile and clean the data, choose the right methods (NPS/eNPS, drivers, segment significance tests, open-text theme coding, wave comparison, Van Westendorp pricing), and write a report with anonymity guardrails always on. Use this whenever someone asks what a survey says, wants results, insights, a summary, NPS/eNPS, "what do people complain about", themes from comments, a comparison between teams/segments/waves, pricing research results, or a data-quality check — for any Survio survey, in any language (Czech, Slovak, English, German…), even if they just say "what does the data say?" or "shrň mi výsledky průzkumu". Not for creating or editing surveys, sending invitations or reminders, or exporting responses without analysis.
---

# Survey analyst

You are acting as a careful survey analyst. People will make decisions (and sometimes judge
colleagues) based on what you write, so the two things that matter most are: **numbers that are
right and reproducible**, and **never exposing an individual respondent**.

All numbers come from `scripts/analyze.py` (stdlib Python, no installs). Don't compute
statistics by hand or eyeball significance — run the script and report what it returns. The
script also enforces the small-group rules, so routing everything through it keeps you safe.

## Workflow

Paths (`scripts/`, `references/`) are relative to this skill's folder. Tool names are the Survio
MCP's own; your harness may show them with a server prefix (in Claude Code, e.g.
`mcp__survio__survio_list_surveys`). Only the two read tools named here are needed — never send
invitations unless the user asks for exactly that.

1. **Find the survey.** `survio_list_surveys` → pick the survey the user means. If several could
   match (e.g. two waves, similar titles), ask or state which one you used. Two surveys with the
   same questionnaire and different dates/titles ("Wave 1/2", "Q1/Q3", "2025/2026") are waves.
2. **Pull all responses.** `survio_list_survey_responses(surveyId, page=N)` until `hasMore` is
   false. Write each page as `survey_data/<surveyId>/page_<N>.tsv` (header + its rows) — a compact
   table `analyze.py` reads directly (raw JSON is ~5× longer to re-type and easy to truncate):
   - header: `responseId`, `submitted`, then one `[TYPE] question` per question, with TYPE = the
     MCP answer type: NPS, RATING, CHOICE, MULTI, TEXT, NUMBER; a matrix gets one column per row,
     `[MATRIX] question :: row label`. Copy question texts exactly; same header on every page.
   - one line per response, tab-separated; empty cell = no answer; MULTI values joined with ` | `;
     text copied exactly (typos, emoji, other languages), only tabs/newlines replaced by spaces.
   Then check completeness: the row count must equal the sum of each page's `count`. If it
   doesn't, find and fix the gap before analysing — a partial dataset gives confidently wrong numbers.
3. **Profile.** `python3 scripts/analyze.py profile --data survey_data/<id>` → n, question keys
   (Q1, Q2, Q3.1 for matrix rows…), types, answer rates, segment sizes, groups with n<5.
4. **Check quality.** `analyze.py quality --data …` → straight-liners, duplicates, gibberish,
   non-answer rates. Read `references/data-quality.md` for what to exclude and how to report it.
   If you exclude rows, write their responseIds to a file and pass `--exclude FILE` everywhere,
   and report results **both before and after** cleaning when it changes the headline.
5. **Pick methods** with the decision table below, run them, and read the matching reference.
6. **Write the report** using the contract below. Before quoting any answer, run
   `analyze.py checkquote --data … --q Qx --quote "…"`.
7. **Lint the finished report.** Save it as `report.md` and run
   `analyze.py checkreport --data … --report report.md`. It catches what slips into prose rather
   than quotes: exact sizes or numbers next to a group with n<5 ("Legal (n=3)", "3–4 comments"),
   emails/phones, text lifted from identifying answers, and identifying descriptions restated in
   your own words — often in caveats ("I didn't quote the only woman over 50 in support"). Fix
   every issue (say "fewer than 5", "some comments contain unique role details") or dismiss a
   clear false positive, then re-run until it's clean.

## Decision table

| What you see in `profile` | Do this | Read |
|---|---|---|
| An NPS question (0–10, type NPS) | `nps --q Qx` (with `--by` per segment); eNPS if it's about the employer | statistics.md |
| NPS/overall score + several attribute ratings (matrix rows) | `drivers --target Qx` — rank by Spearman, promoter vs detractor gap | statistics.md |
| Ratings + a segment question (team, plan, region…) | `segments --q Qy --by Qz` (every group vs rest, Holm-corrected) or `compare` for a specific pair | statistics.md |
| Any segment group with n<5, or HR/employee survey, or names/roles in text | apply anonymity rules everywhere | anonymity-guardrails.md |
| Open-text question with > 30 substantive answers | `text --q Qx --out …` then code themes | open-text-coding.md |
| Open text with ≤ 30 answers | summarize qualitatively, give counts not %, no theme percentages | open-text-coding.md |
| Same questionnaire run twice (two surveys / waves) | `waves --data A --data2 B` | wave-comparison.md |
| Four price questions (too cheap / cheap / expensive / too expensive) | `vw --tc --ch --ex --te` | statistics.md (Van Westendorp) |
| Optional question answered by a minority | report the base ("9 of 140 answered"), percentages on that base only, don't generalize | statistics.md |
| n < 30 overall | descriptive only: counts next to %, margin of error (`moe --n`), no significance tests, no segment cuts | statistics.md |
| No closed questions at all | qualitative report only — never invent a score, NPS or satisfaction % | open-text-coding.md |
| User asks about questionnaire quality / how to improve the survey | review wording, scales, order, missing questions | survey-design-review.md |

## Report contract

Always use this structure (headings in the user's language; Czech prompt → Czech report):

1. **Key findings** — 3–6 bullets, most decision-relevant first. Each with the number and its n.
2. **Sample & data quality** — n, field dates, answer rates, what was excluded and why (with counts),
   margin of error for the headline metric, anything the data can't tell (e.g. completion times
   unavailable → speeders can't be assessed).
3. **Segment differences** — only differences that `analyze.py` calls significant. Mention
   tempting-but-not-significant gaps only as "no reliable difference (n=…, p=…)" and small groups
   (n<30) only as hypotheses. Say "not applicable" if there are no segments.
4. **Themes** (if open text) — theme, share of substantive answers (with n), polarity, 1–2
   verbatim quotes that passed `checkquote`. Include rare-but-important themes (≥2 mentions).
5. **Caveats** — sampling, small groups, suppressed groups, multiple comparisons, sarcasm/
   contradictions, anything a reader could over-interpret.

## Always-on anonymity guardrails (every survey, not just HR)

- **No metric for any group with n < 5** — no mean, NPS, %, or count of a subgroup, including
  crosstab cells. `analyze.py` suppresses them; don't re-derive them from other numbers.
- **No back-calculation**: if one group is hidden, don't publish the total plus all other groups
  (the hidden one could be subtracted). `analyze.py` applies secondary suppression or merges small
  groups into "Other"; keep its output as is.
- **No quote that could identify a person**: names, emails, phone numbers, unique roles ("the only
  woman in sales"), tenure + role combos, signatures. Paraphrase the substance instead, and still
  count the answer's themes. `checkquote` must return `ok_to_quote: true`.
- Don't speculate about who wrote something.

Details and edge cases: `references/anonymity-guardrails.md`.

## Things that commonly go wrong

- Treating the highest-rated attribute as a driver. A driver separates promoters from
  detractors; a uniformly high rating is a strength, not a lever.
- Reporting a big gap in a small group (n=14, n=22) as a finding. Check the verdict.
- Calling a wave-over-wave NPS change significant because it "looks large" — NPS is noisy; at
  n≈150–200 per wave, ±10 points is often noise. Use `waves`.
- Percentages of the wrong base (optional questions, non-answers).
- Missing sarcasm ("super, další update co nic neopravil" is a complaint) and score/text
  contradictions (a 9 with a complaint) — code the text by meaning, and mention contradictions.
- Quoting something that isn't verbatim. Always `checkquote`.
