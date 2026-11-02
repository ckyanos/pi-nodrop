# Documentation

Public documentation contains usage instructions, reproducible experiment
reports, and portable result summaries. Reports describe their recorded source
version and protocol; historical results do not validate a newer baseline.

## Current baseline and comparisons

- [NoDrop upstream update](nodrop-update-20261102.md): current source version,
  adaptation changes, and the unresolved native validation failure.
- [Five-condition comparison](fiveway-comparison.md): native Pi and Harbor with
  baseline, AgentSight, AgentSentinel, fixed raw NoDrop, and agent-selected policy.
- [External audit reproduction](external-agent-audit-reproduction.md): native
  collectors, analysis stages, compatibility changes, and reproduction details.

## Audit interfaces and output handling

- [Tool-call policy field](agent-policy.md): submitting audit policy with the
  original business arguments.
- [Output references](output-references.md): storing and retrieving long
  business-tool outputs independently of audit retention.
- [Test credentials](test-credentials.md): environment selection and credential
  handling for experiment entry points.

## Benchmark protocols

- [Harbor integration](harbor-comparison.md): original Pi execution and verifiers.
- [Field interface comparison](harbor-field-comparison.md): the three-condition
  field-based policy experiment.
- [Historical task runner](terminal-bench.md): earlier custom-runner results.
- [Initial native integration](experiment-report.md): the original functional
  capture and attribution checks.

## Historical experiments

These reports preserve earlier configurations, including superseded interfaces
and runs with explicit budgets or deadlines.

| Topic | Reports |
| --- | --- |
| Initial audit comparisons | [Token comparison](token-comparison.md), [Control replay](control-comparison.md), [Optimized comparison data](optimized-comparison-results-20261029.json) |
| Fixed and agent-selected policy | [Fixed raw](live-fixed-raw.md), [Agent policy](live-agent-policy.md), [Optimized agent policy](live-agent-policy-optimized.md), [Three conditions](three-way-comparison.md) |
| Model configuration | [API-managed fixed raw](api-managed-fixed-raw.md) |
| Output presentation | [Output references across conditions](reference-comparison.md) |
| Policy interface development | [Context optimization](agent-policy-optimization.md), [Policy generation](policy-generation.md), [Tool-name interface](policy-tool-names.md), [Harness comparison](harness-comparison.md), [Missing-policy analysis](field-policy-omissions.md) |
| Provider compatibility | [Strict support](strict-api-support.md), [Official API probe](strict-official-api-support.md), [Model matrix](strict-model-matrix.md), [Native protocol routes](vendor-protocol-route-checks.md), [Schema constraints](tool-schema-constraint-protocols.md) |

Machine-readable summaries remain alongside their reports as dated JSON files.
Reusable configurations are under `experiments/`; full raw records are retained
locally under `results/`.
