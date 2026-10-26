# Data quality

Run `analyze.py quality` before any analysis. It flags:

| Flag | Meaning | Default action |
|---|---|---|
| `straight_liner` | identical answer on every row of a matrix with ≥5 rows | exclude |
| `duplicate_of:<id>` | every answer (incl. substantive text) identical to an earlier response | exclude one of each pair |
| `gibberish` | keyboard mash / random letters / "test test" in open text | exclude the row if the closed answers also look careless; otherwise just drop the text |
| `speeder` | completion time < ⅓ of median (only if times were supplied) | exclude |

Then look at the open text yourself — the heuristics miss some gibberish ("bna jni") and you should
catch it while coding.

## Completion times / speeders
The Survio MCP response payload does not include completion time, and its completionTime filters
are not reliable. Unless the user provides times (e.g. an export), state in the report:
"Completion times were not available, so speeders could not be identified." Don't guess speeders
from answer patterns alone — call those rows what they are (straight-liners, near-constant answers).

## Reporting
- Always report: n received, n excluded by reason (counts), n analyzed — and every flag count
  from `quality`, including flags that didn't lead to exclusion ("10 gibberish texts dropped,
  ratings kept"). Even when the user only asks for averages, the reader needs to know how much
  of the data was junk to judge how far to trust it.
- If cleaning changes a headline metric noticeably, show both ("raw 3.63 → 3.50 after removing
  55 low-quality responses"); readers need to see the effect.
- Duplicates: say they are identical submissions; you can't know which one is the "original" —
  keep the first, drop the later one.
- Non-answers ("ok", "-", "nic", emoji only) are normal; report the share, don't exclude the
  respondent for them.
- Write excluded responseIds to a file and pass `--exclude FILE` to every later command so all
  numbers use the same base.
