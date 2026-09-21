# Harbor: Claude Code trajectory rejected on a self-inflicted step-id gap

**Component:** `harbor/agents/installed/claude_code.py` (harbor 0.9.0, aws-bench 0.7.0).

**Symptom.** `_convert_events_to_trajectory` builds an ATIF trajectory that
`Trajectory` then refuses, so the trial ends with no `agent/trajectory.json`
while the session JSONL and stream transcript on disk are complete, and every
`AgentContext` token field stays `None`. Logged at DEBUG as "Failed to convert
Claude Code events to trajectory":

    1 validation error for Trajectory
      Value error, steps[16].step_id: expected 17 (sequential from 1), got 18

**Affected trials** (both complete, reward 1.0): `ecs-swappiness-awscdk__vg96pLR`
(`jobs/amend43-promotion/2026-09-21__00-34-05`, `steps[16]`) and
`named-resource-replacement-terra__saaxzSo`
(`jobs/amend32-promotion/2026-08-27__21-50-09`, `steps[17]`, expected 18 got 19).

**Cause, at the gap.** `raw_events.sort(key=lambda e: e.get("timestamp", ""))`
reorders a tool result ahead of its own `tool_use`: the result for
`toolu_01PFT93vS8qQTd7kDgjZKvZj` is stamped `17:39:43.378Z`, the assistant
message that issued it `17:39:43.395Z`. The result is normalized before the call
reaches `pending_calls`, so a `call_info` with `tool_name: ""` is synthesized,
`_convert_event_to_step` raises `Tool call event missing call_id or tool_name`,
and the loop `continue`s while its `enumerate(..., start=1)` index does not.

**Suggested fix.** Number steps as they are appended (so a skipped event cannot
create a gap), or accept gaps in `step_id`. Independently: pair a `tool_result`
to its `tool_use` by id in file order, not by timestamp.
