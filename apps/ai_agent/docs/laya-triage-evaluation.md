# Laya triage smoke evaluation — 2026-10-07

Command: `python -m scripts.check_laya_triage` using the installed Laya package
and `convaiinnovations/laya` English checkpoint. No cloud LLM was called.

Ten short, hand-written inputs covered SQL locking and syntax errors,
connection refusal and DNS failure, bad credentials and denied permissions,
missing and invalid settings, a successful backup, and a greeting.

- Category matched the expected label in 10/10 examples.
- Investigation was Yes for all eight issue examples and No for the two
  non-issue examples.
- Severity was Warning for six issue examples and Informational for two
  (SQL syntax error and denied permissions). Both non-issue examples were
  Informational. Severity is a model judgment, not a verified impact assessment.
- Every example was marked uncertain at the initial 0.70 threshold because at
  least one answer had lower confidence; category Unknown also forces review.

These are smoke examples, not a held-out benchmark. They demonstrate the
runtime and response contract, not general accuracy or calibrated confidence.
Keep classifications advisory; test representative local logs and issue
descriptions before changing the threshold or using a result to trigger work.
No threshold was lowered to make this evaluation look more confident.

The package also emitted a checkpoint-temperature warning for `choice:11+`;
this triage schema uses five and three choices, but no confidence-calibration
claim is made for either. No generative-model fallback is configured.
