# Open-text coding

## Process
1. Export: `analyze.py text --data … --q Qx --out coded_input.json` → each answer with id,
   non-answer/gibberish/PII flags.
2. **Read every substantive answer** (don't sample when n ≤ 500). Answers can be in Czech,
   Slovak, English, German, mixed ("support je fakt slow"), without diacritics, with typos —
   code them by meaning, not by keyword.
3. Build a codebook bottom-up: draft themes after ~50 answers, then refine. Aim for 5–10 themes
   with clear definitions; merge near-duplicates; keep a theme even if rare when it's specific and
   actionable (data export/GDPR, accessibility, a legal issue) — rare themes are often the most
   valuable.
4. Code each answer to 0..n themes (multi-theme answers are common — count each theme), with
   polarity (+ praise / − complaint or request). Save codes to a file
   (`{"id": [{"theme":..,"polarity":..}]}`) so counts are reproducible; count with a short script.
5. Report each theme: count, share of substantive answers (state the base), polarity mix, and
   1–2 verbatim quotes that passed `checkquote`. Order by share.

## Judgment calls
- **Sarcasm/irony**: "super, další update co nic neopravil", "Love paying more every year" →
  negative. Code the real meaning.
- **Contradictions**: NPS 9–10 with a complaint, or 0–3 with praise. Code the text as written,
  and mention in caveats that a share of scores and comments disagree (with count).
- **Wrong question / off-topic / rants**: don't force them into product themes; count them as
  "off-topic" and don't quote rants with profanity.
- **Vague** ("could be better", "depends"): substantive but no theme — don't invent one.
- **Copy-paste across questions**: count once per question it appears in, but mention if notable.
- **Identifying answers**: code their themes, never quote them (see anonymity-guardrails.md).
- Translate quotes only if the report language differs — then give the original + translation.

## Small text sets (≤ 30 substantive answers)
Give counts ("4 of 9"), not percentages, and don't claim a theme is "the main issue" for the
population.
