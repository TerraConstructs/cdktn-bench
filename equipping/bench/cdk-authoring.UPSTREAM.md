<!-- Provenance for equipping/bench/cdk-authoring{,-stale}/. Deliberately NOT
     inside either skill directory: the generator copies a skill directory into
     the agent's container, and this file names the study. -->

# What this skill stands in for, and why it is bench-written

Prereg §2.2 names the AWSCDK arm's tuned row as "AWS MCP + AWSCDK agent-tool
plugins / Kiro Powers + AWS Docs MCP". The agent-tool plugin AWS actually ships
is the Kiro power `aws-infrastructure-as-code` in `kirodotdev/powers`
(`aws-infrastructure-as-code/POWER.md`, `aws-infrastructure-as-code/mcp.json`,
read 2026-09-24).

**It cannot be vendored.** That repository ships no LICENSE file, and its
README grants only "a non-exclusive license to access, download, and otherwise
use the power for their personal or business purposes" to Kiro users — no
redistribution grant, so copying its prose into this repository or into an arm
image is not permitted. `scripts/vendor_equipping.pins.json` records the quote.

**What is taken, and what is not.** The power's *MCP configuration* is a factual
pin and is reused: `awslabs.aws-iac-mcp-server` (Apache-2.0, `awslabs/mcp`,
pinned 1.0.26), whose credential-free tools are `search_cdk_documentation`,
`search_cdk_samples_and_constructs`, `cdk_best_practices`,
`read_iac_documentation_page` and `search_cloudformation_documentation`. The
power's *prose* is not taken: `SKILL.md` beside this file is written here, from
the public CDK documentation and from this arm's own pinned versions
(`aws-cdk-lib` 2.263.0, `constructs` 10.8.1, CDK CLI 2.1135.0 —
`arms/awscdk/environment/Dockerfile`).

**The consequence for the result.** The AWSCDK tuned cell is therefore
"pinned AWS IaC MCP + AWS Docs MCP + a bench-written authoring skill", not
"the Kiro power". That is a deviation from prereg §2.2's wording and must be
registered as such; it is a licence constraint, not a design preference.
