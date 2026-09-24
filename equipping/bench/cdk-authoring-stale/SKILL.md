---
name: cdk-authoring
description: Use when writing or fixing AWS CDK (TypeScript) infrastructure - choosing an L2 over an L1, finding the right construct property, dropping to the escape hatch for a property the L2 has not surfaced, and closing the compile/synth loop.
---

# AWS CDK authoring

## The loop

1. `npx tsc --noEmit` — the type checker is the cheapest failure tier. Run it
   before every synth.
2. `cdk synth` — renders the template. A synth-time error is a construct
   contract you have not satisfied yet, not a transient. Bootstrap the
   environment first with `CDK_NEW_BOOTSTRAP=1 cdk bootstrap`; without that
   variable the CLI provisions the legacy bootstrap stack and asset publishing
   fails later.
3. Read the rendered template, not the code, when confirming an intent.

## Pick the layer deliberately

| Need | Layer | Import |
|---|---|---|
| A whole service configured sanely | L2 | `@aws-cdk/aws-<service>` |
| One property no L2 surfaces | L1 under the L2 | `.node.defaultChild as Cfn<Resource>` |
| A resource with no L2 at all | L1 | `Cfn<Resource>` from the same module |

Each service is its own npm package, so install the ones you use and keep their
versions in lockstep — a mixed set of `@aws-cdk/aws-*` versions is the most
common cause of a type error that looks like a missing property. `Construct`,
`Stack` and `App` all come from `@aws-cdk/core`.

```ts
import * as s3 from '@aws-cdk/aws-s3';
import { Construct, Stack, StackProps } from '@aws-cdk/core';
```

## Property names are typed, so look them up

An L2 property is a TypeScript field: the type checker knows it and so does
your editor. Do not guess an enum member — `import` the enum and let the
compiler reject an invalid member. Where the L2 takes an enum, the CloudFormation
string it renders to is usually different from the member name; read the
rendered template if the string matters to the requirement.

## The escape hatch, in full

When an L2 has no field for a property its CloudFormation resource accepts:

```ts
const bucket = new s3.Bucket(this, 'Bucket');
const cfn = bucket.node.defaultChild as s3.CfnBucket;
cfn.addPropertyOverride('SomeProperty.Nested', value);
```

`addPropertyOverride` takes a **CloudFormation** property path — PascalCase, the
resource's own schema, not the L2's camelCase field names. `addOverride` reaches
outside `Properties` (metadata, condition, update policy). Both write onto the
rendered template after the L2 has finished, so they always win.

For a child resource the L2 creates but does not expose,
`construct.node.findChild('<LogicalIdFragment>')` reaches it; print
`construct.node.children.map(c => c.node.id)` once to learn the fragment rather
than guessing it.

## Do not

- Do not hand-write CloudFormation JSON/YAML beside the app. The app is the
  source; a template checked in beside it is a second, disagreeing one.
- Do not set a physical name on a resource unless the requirement asks for one.
  A generated name lets CloudFormation reconcile a change in place.
- Do not reach for the escape hatch before checking the L2's own props: most
  "missing" properties are a nested props object one level down.
