# Anonymity guardrails

These apply to every survey. Customer surveys contain identifying details too ("I'm the owner of
the only physio clinic in Třebíč"), and segment cuts can single out individuals in any dataset.

## Small groups (n < 5)

- Never report any statistic for a group with fewer than 5 respondents: no mean, NPS/eNPS,
  percentage, top-box, distribution, or even "most of them said…".
- This includes **cells of crosstabs** (team × tenure, region × plan). A team of 12 split by
  tenure easily produces cells of 2–3.
- It's fine to say a group exists and was not reported: "Two teams have fewer than 5 respondents
  and are not reported separately."
- Don't reveal the group's size precisely if that itself is sensitive (e.g. "Legal: 3 people").
  Say "fewer than 5".
- A "group" here means respondents defined by their answer to a closed segment question (team,
  role, plan, region, tenure…). How many people mention a theme, or how many gave a rating of 1,
  is *not* a group: report those counts normally ("export: 4 complaints, 4 praise"). Hiding them
  protects no one and hides rare-but-important themes. The risk in open text is quoting or
  describing an identifying answer, not counting it.

## Secondary suppression (back-calculation)

If you show the overall number and every group except one, a reader can compute the hidden group:
`hidden = (total·N − Σ shown_i·n_i) / n_hidden`. Prevent this:

- Prefer merging small groups into **"Other (merged)"** when the merged group has n ≥ 5.
- If merging isn't possible, also hide the next-smallest group (analyze.py does this).
- Don't publish the total n and per-group n's in a way that lets someone infer the hidden n
  together with an extreme value (e.g. overall eNPS +18 with every team listed except one).
- Don't run `compare` on a small group "just to check" and then describe the result.

## Identifying text

An answer is identifying if a colleague, manager, or customer could reasonably guess who wrote it:
- personal names (respondent's or others'), signatures ("— Jana K."), emails, phone numbers;
- unique roles: "the only DevOps engineer", "jako jediná žena v salesu", "vedoucí směny B";
- tenure + role combos: "after 11 years leading Support";
- demographic details that are unique in a team: age, gender in a small team, location;
- very specific events ("the person whose vacation was cancelled on Monday").

Rules:
- Don't quote it, not even partially or with the name removed — the remaining context often still
  identifies. **Paraphrase the substance** ("one person in a leadership role mentions understaffing").
- Still count its themes in theme statistics; the content matters, the identity doesn't.
- Never repeat emails/phones/names anywhere in the report, including tables and appendices.
- `analyze.py checkquote` flags common patterns, but it isn't perfect — use judgment; when in doubt,
  paraphrase.

## HR surveys specifically

- Report team results only for teams with n ≥ 5; prefer n ≥ 10 for anything evaluative about a
  manager.
- Don't describe the sentiment of an individual manager's team if the team is small, even
  qualitatively.
- Frame findings at the level of themes and groups, never individuals.
