"""Blast radius: how much infrastructure a solution's change actually moves.

The read is `resource_changes[]` of a Terraform plan, never `planned_values`:
that array is already flat, carries `module_address` and instance-keyed
addresses, and holds the `change.actions` list this counts. `planned_values` is
a nested desired-state tree with no actions in it at all, so it can express
"what will exist" but not "what gets replaced".

One `resource_changes[]` element falls in exactly one bucket, keyed on its
`change.actions`:

    ["no-op"]                          -> no_op
    ["create"]                         -> create
    ["read"]                           -> read      (a data source read)
    ["update"]                         -> update    (in place)
    ["delete"]                         -> delete
    ["create", "delete"]               -> replace   (create before destroy)
    ["delete", "create"]               -> replace   (destroy before create)

Anything else (`["forget"]`, a future action pair) is counted in `other` AND
listed verbatim in `unclassified_actions`, so an action Terraform adds later is
visible as unclassified rather than silently absorbed into a named bucket.

`root` vs `module` splits on a non-empty `module_address`, which is the
compression claim under test: an abstraction that emits the same change through
a module call moves the same resources from a different authoring surface.

**awscdk carries less, and says so.** Absent a deployment there is no
CloudFormation changeset, so the equivalent read is the synthesized template's
own `Resources` count: `total` is that count, `source` is
`cloudformation-template`, and `counts`/`root`/`module` are all null -- a
template states what will exist, not what a deployment would do to what is
already there. A changeset-backed read (`source: cloudformation-changeset`,
`Changes[].ResourceChange.Action`/`Replacement`) fills the same buckets and is
what a live awscdk trial can upgrade to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PLAN_SOURCE = "terraform-plan"
TEMPLATE_SOURCE = "cloudformation-template"
CHANGESET_SOURCE = "cloudformation-changeset"

# The raw plan, as the toolchain wrote it. The normalised copy beside it is
# persisted for the same reason but never read here: the normaliser rewrites
# the values/config side and leaves `resource_changes` alone, so reading it
# would answer the identical question off a document one transform further from
# what Terraform said.
PLAN_NAME = "plan.json"
TEMPLATE_SUFFIX = ".template.json"

_ACTION_BUCKETS = {
    ("no-op",): "no_op",
    ("create",): "create",
    ("read",): "read",
    ("update",): "update",
    ("delete",): "delete",
    ("create", "delete"): "replace",
    ("delete", "create"): "replace",
}
BUCKETS = ("create", "update", "delete", "replace", "no_op", "read", "other")


class BlastRadiusUnavailable(Exception):
    """No artifact this trial persisted answers the question."""


def bucket_for(actions: Any) -> str:
    """Bucket name for one `change.actions` value; `other` for anything the
    mapping above does not name."""
    if not isinstance(actions, list):
        return "other"
    return _ACTION_BUCKETS.get(tuple(str(a) for a in actions), "other")


def from_plan(plan: Any) -> dict[str, Any]:
    """Blast radius of a Terraform plan document."""
    if not isinstance(plan, dict):
        raise BlastRadiusUnavailable("plan artifact is not a JSON object")
    changes = plan.get("resource_changes")
    if not isinstance(changes, list):
        raise BlastRadiusUnavailable(
            "plan artifact has no resource_changes[] array "
            "(a plan produced by `terraform show -json` always does)"
        )
    counts = dict.fromkeys(BUCKETS, 0)
    unclassified: list[list[str]] = []
    root = module = 0
    for entry in changes:
        if not isinstance(entry, dict):
            raise BlastRadiusUnavailable("a resource_changes[] element is not an object")
        actions = (entry.get("change") or {}).get("actions")
        name = bucket_for(actions)
        counts[name] += 1
        if name == "other":
            unclassified.append([str(a) for a in actions] if isinstance(actions, list) else [])
        if entry.get("module_address"):
            module += 1
        else:
            root += 1
    out: dict[str, Any] = {
        "source": PLAN_SOURCE,
        "total": len(changes),
        "root": root,
        "module": module,
        "counts": counts,
    }
    if unclassified:
        out["unclassified_actions"] = unclassified
    return out


def from_template(template: Any) -> dict[str, Any]:
    """Blast radius of a synthesized CloudFormation template: the resource
    count only. No action breakdown exists without a changeset."""
    if not isinstance(template, dict):
        raise BlastRadiusUnavailable("template artifact is not a JSON object")
    resources = template.get("Resources")
    if not isinstance(resources, dict):
        raise BlastRadiusUnavailable("template artifact has no Resources object")
    return {
        "source": TEMPLATE_SOURCE,
        "total": len(resources),
        "root": None,
        "module": None,
        "counts": None,
    }


def from_changeset(changeset: Any) -> dict[str, Any]:
    """Blast radius of a `DescribeChangeSet` response: the same buckets a plan
    fills, from `Changes[].ResourceChange`."""
    if not isinstance(changeset, dict):
        raise BlastRadiusUnavailable("changeset artifact is not a JSON object")
    changes = changeset.get("Changes")
    if not isinstance(changes, list):
        raise BlastRadiusUnavailable("changeset artifact has no Changes[] array")
    counts = dict.fromkeys(BUCKETS, 0)
    unclassified: list[list[str]] = []
    for entry in changes:
        rc = (entry or {}).get("ResourceChange") or {}
        action = str(rc.get("Action") or "")
        replacement = str(rc.get("Replacement") or "")
        if action == "Add":
            name = "create"
        elif action == "Remove":
            name = "delete"
        elif action == "Modify":
            # `Conditional` is CloudFormation declining to promise; it is not
            # evidence of an in-place update, so it counts as a replace.
            name = "update" if replacement == "False" else "replace"
        elif action == "Import":
            name = "read"
        else:
            name = "other"
            unclassified.append([action or "?", replacement or "?"])
        counts[name] += 1
    out: dict[str, Any] = {
        "source": CHANGESET_SOURCE,
        "total": len(changes),
        "root": None,
        "module": None,
        "counts": counts,
    }
    if unclassified:
        out["unclassified_actions"] = unclassified
    return out


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise BlastRadiusUnavailable(f"{path.name} is unreadable: {exc}") from exc


def from_artifacts_dir(artifacts: Path) -> tuple[dict[str, Any], Path]:
    """`(blast_radius, artifact_path)` for one collected-artifacts directory.

    Dispatch is on the persisted file name, which the verifier controls: the
    raw plan keeps the name `plan.json` on every Terraform-shaped arm, and a
    CloudFormation template keeps `<Stack>.template.json`.
    """
    plan = artifacts / PLAN_NAME
    if plan.is_file():
        return from_plan(_read(plan)), plan
    templates = sorted(p for p in artifacts.glob("*" + TEMPLATE_SUFFIX) if p.is_file())
    if len(templates) == 1:
        return from_template(_read(templates[0])), templates[0]
    if templates:
        raise BlastRadiusUnavailable(
            f"{len(templates)} *{TEMPLATE_SUFFIX} artifacts persisted; "
            "which stack the row describes is not decidable"
        )
    raise BlastRadiusUnavailable(
        f"no {PLAN_NAME} or *{TEMPLATE_SUFFIX} under {artifacts.name}/"
    )
