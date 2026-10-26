# Statistics guide

All numbers come from `scripts/analyze.py`. This file explains how to read and report them.

## NPS / eNPS
- NPS = % promoters (9–10) − % detractors (0–6), range −100…+100. eNPS = the same for "would you
  recommend us as an employer".
- Always report n and the 95% CI (`nps` returns it). At n=150 the CI is roughly ±10–12 points.
- Report NPS as a whole number with sign (+12, −15). Not a percentage.

## Significance: how to read `compare` / `segments` / `waves`
Each comparison runs four tests (chi² on categories, Mann-Whitney, Welch t, bootstrap):
- **significant** — all four agree at p < 0.05. You may report it as a difference.
- **borderline (tests disagree)** — mention cautiously or not at all; never as a finding.
- **not significant** — say there's no reliable difference, even if the gap looks big.
- **inconclusive — a group has n<30** — a hypothesis worth watching, not a result.
- **significant (small group, n=…)** — evidence is strong despite small n; report with n.
- `segments` applies a Holm correction across groups; use `p_holm_worst_test` when many groups are
  compared. Don't go fishing through dozens of cuts and report the one that "worked".

Report effect sizes in the scale's own units (e.g. "+0.6 points on a 1–5 scale", "+20 pp
top-2-box", "+15 NPS points"), always with both n's.

## Drivers
- `drivers --target <NPS or overall>` ranks matrix attributes by Spearman ρ with the target and
  shows promoter vs detractor means.
- A **driver** has a clear relationship (ρ ≳ 0.3 and a significant promoter/detractor gap).
- A **non-driver** can have the highest average rating. It's a strength to keep, not a lever.
- Correlation ≠ causation; phrase as "most strongly associated with".
- Don't include the overall satisfaction question as a "driver" of NPS — it's another outcome.

## Small samples
- n < 30 overall: describe with counts ("7 of 12"), give the margin of error (`moe --n 12` →
  ±28 pp), skip significance tests and segment splits (which would also create n<5 cells).
- Any group n < 30: descriptive only unless the script says the evidence is strong.

## Bases and optional questions
- Percentages need a stated base. For an optional question: "9 of 140 respondents answered;
  among them 4 mention shipping cost". Never "3% mention shipping cost" based on 140, and don't
  generalize from 9 people to all customers.
- Non-answers ("ok", "-", "nevím") are not substantive; theme shares use substantive answers as
  the base, and say so.

## Van Westendorp
- `vw` excludes logically inconsistent rows (too cheap ≥ cheap ≥ expensive ≥ too expensive must
  increase); report how many were excluded.
- Acceptable price range = PMC (lower) … PME (upper). OPP = optimal price point, IPP =
  indifference price point. Different tools use slightly different curve conventions; state the
  convention line from the output and round sensibly (±10 CZK).
- Segment ranges only for segments with n ≥ 30.

## Margin of error
`moe --n N` gives the worst-case 95% MoE in percentage points. Use it for the headline % in the
"sample & data quality" section.
