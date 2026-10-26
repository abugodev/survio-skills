# Wave comparison

Use when the same questionnaire was run more than once (two surveys with the same questions, or
one survey whose title/date marks a new wave).

1. Pull both surveys into separate folders. Confirm the questions match (`profile` on both); only
   compare identical questions and scales.
2. `analyze.py waves --data <wave1> --data2 <wave2>` → per item: wave 1, wave 2, change, four
   tests, verdict. For ratings it also tests the top-2-box share.
3. Segment-level change: `--by Qx` (segments with n ≥ 5 in both waves only). Small segments
   (n < 30 per wave) swing a lot by chance — report as hypotheses at most.
4. Report:
   - significant shifts: direction, size in scale units/pp, both n's;
   - big-looking but non-significant shifts explicitly as "within noise" (NPS at n≈150–200 per
     wave moves ±10 points by chance);
   - stable items briefly;
   - open-text theme shifts if both waves have text: compare theme shares and test the biggest
     change with a 2×2 chi² (`compare`-style reasoning), stating bases.
5. Don't attribute causes to changes unless the user tells you what changed between waves.
