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

| date | arm | reward | output tok | num_turns | cost $ | agent wall | live_check | job |
|------|-----|-------:|-----------:|----------:|-------:|-----------:|:----------:|-----|
| 2026-08-13 | hcl-raw | 1.0 | 45,535 | 49 | 2.28 | 841s | 3/3 pass | jobs/g-live-hcl-2/2026-08-13__15-34-38 |
| 2026-08-13 | awscdk  | 1.0 |  9,403 | 33 | 0.75 | 394s | 3/3 pass | jobs/g-live-awscdk-1/2026-08-13__18-11-19 |

**First cross-arm read (n=1 per arm, directional only):** awscdk reached green
with ~4.8x fewer output tokens, 1.5x fewer turns, 3x lower cost. Caveat: this
scenario is CDK-favorable by construction — its catch is the salted-deployment
logical-id that CDK's `RestApi` L2 emits automatically but HCL must wire by hand
(`aws_api_gateway_deployment` triggers/redeployment). Expect the gap to narrow on
scenarios without such a sharp L2 advantage. Not yet run: the `terraconstructs`
arm of this scenario; repeat trials for variance.

### Superseded / context
- The very first live trial (`apigw-redeploy-hcl-raw`, 8-turn budget) was
  right-censored by a config bug (`error_max_turns` at 8 turns), reward 0.0 —
  NOT a real failure. Motivated the turn-budget fix (Amendment 22). Excluded.
