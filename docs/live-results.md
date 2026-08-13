# Live trial results (running log)

Append-only log of real, billed, live-verified trials. Headline denominator is
**output tokens** (DECISIONS.md Amendment 23); `cost_usd` reported alongside as
cost-of-ownership. These are PILOT data points (n small) — not a scored result
until enough trials exist per cell for the pre-registered estimators
(Kaplan-Meier tokens-to-green, Wilson success-rate). Do not aggregate into a
headline before the census is adequate.

All trials: `claude-code` / `claude-sonnet-5`, env `cdktn-anchor`, account
886312446417 us-east-1, 100-turn backstop, `MAX_TOKENS` unset (token-uncensored
pilot), mutating scenarios run the agent as `QALocalInvocationApplicationAdmin`
(Amendment 24).

## apigw-redeploy (live: apply → add /status route → re-apply → verify)

| date | arm | reward | output tok | num_turns | cost $ | live_check | job |
|------|-----|-------:|-----------:|----------:|-------:|:----------:|-----|
| 2026-08-13 | awscdk          | 1.0 |  9,403 | 33 | 0.75 | 3/3 pass | jobs/g-live-awscdk-1/2026-08-13__18-11-19 |
| 2026-08-13 | terraconstructs | 1.0 | 24,218 | 80 | 3.34 | 3/3 pass | jobs/g-live-tcons-1/2026-08-13__18-36-36 |
| 2026-08-13 | hcl-raw         | 1.0 | 45,535 | 49 | 2.28 | 3/3 pass | jobs/g-live-hcl-2/2026-08-13__15-34-38 |

**First full three-arm read (n=1 per arm — directional only, NOT significant):**

- **Output tokens (the denominator) order the arms exactly as the thesis
  predicts:** awscdk 9.4k < terraconstructs 24.2k < hcl-raw 45.5k. aws-cdk-lib
  (most mature L2) needs the least authoring; terraconstructs (typed, but younger
  L2 over a Terraform backend) sits in the middle (~2.6x fewer than HCL, ~2.6x
  more than awscdk); raw HCL needs the most.
- **Turns tell a different, independent story:** terraconstructs took the MOST
  turns (80) despite writing far fewer tokens than HCL (49) — it authored less
  but *iterated more*, likely wrestling with `cdktn synth`/coverage friction.
  Output-tokens (authoring effort) and turns (interaction friction) are separate
  axes; the thesis rides on the former.
- **Cost inverts vs tokens:** terraconstructs is the MOST expensive ($3.34 >
  hcl-raw $2.28) despite fewer output tokens, because 80 turns → 7.48M cache-read
  (context replayed each turn dominates billed cost). This is exactly why
  Amendment 23 put the metric on output tokens, not cost/cache — cost tracks
  turn count, not authoring skill.

**Caveats.** n=1 per arm; no variance. This scenario is CDK-favorable by
construction — its catch is the salted-deployment logical-id that CDK's `RestApi`
L2 emits automatically but HCL must wire by hand (`aws_api_gateway_deployment`
triggers). Expect gaps to narrow on scenarios without such a sharp L2 advantage.
Next: repeat trials for variance; more scenarios for generality.

### Superseded / context
- The very first live trial (`apigw-redeploy-hcl-raw`, 8-turn budget) was
  right-censored by a config bug (`error_max_turns` at 8 turns), reward 0.0 —
  NOT a real failure. Motivated the turn-budget fix (Amendment 22). Excluded.
