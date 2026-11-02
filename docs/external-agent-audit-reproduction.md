# AgentSight and AgentSentinel reproduction

## Setup

The local smoke experiment uses Linux 6.8.0-137-generic, four virtual CPUs,
4 GiB of memory, Docker, and DeepSeek V4.1 Flash (1017) through iBrain.
Both iBrain model aliases refer to the same model. Requests use `project-ak-api`.

The task reads a three-row CSV, sums values by name, writes `result.json`, and
checks the result against `{"alpha": 7, "beta": 3}`. A small Python tool-use
harness runs the same task in each condition. This is a mechanism smoke test;
Terminal-Bench task accuracy and attack-detection accuracy are separate evaluations.

| Project | Upstream revision |
| --- | --- |
| [AgentSight](https://github.com/eunomia-bpf/agentsight) | `892ee9c2c33e492506444aefe67adf95960c7316` |
| [AgentSentinel](https://github.com/m4p1e/agent-sentinel) | `c3e25e6678c4c77cfba74c91bcda306567b1defd` |

AgentSight uses the July 2025 implementation associated with the paper-era
architecture. Its collector captures process events and decrypted TLS traffic.
The upstream correlation script and semantic-analysis prompt process the captured
trace. The semantic analyzer makes a real iBrain request; its mock fallback is
disabled. Its upstream sampling of at most 20 trace entries is retained.

AgentSentinel receives tool-use messages through its original Python client and
Unix socket. The native tracer, context summarizer, security auditor, rules, and
caches remain active. Its original OpenAI client is routed to iBrain; the CLI
selector `openai/gpt-4o` selects the client implementation, while the gateway
submits DeepSeek V4.1 Flash (1017).
The upstream CLI defaults are retained: `process-trace-level=0`,
`binary-level-cache=false`, `tool-use-timeout=60`, and `EventCountLimit=20`.

## Local adaptations

- A loopback TLS gateway keeps the real credential outside captured agent traffic
  and records the provider's usage for each request.
- The harness and gateway send each small HTTP message in one TLS write to match
  AgentSight's stateless HTTP parser. The native producers exit and drain their
  output before the Rust consumer exits.
- AgentSentinel resolves the container's current cgroup and Bash binary through
  its host PID, supporting Docker's current storage layout.
- AgentSentinel's eBPF objects are regenerated against the running kernel BTF.
  The inode ctime accessor uses the Linux 6.8 field. The task-kill LSM denial
  returns `-EPERM`, as required by the verifier. The VM enables BPF LSM.

The original audit prompts and decision paths are retained. Single-response
output limits follow the upstream clients; the harness adds no cumulative token,
turn, or tool-call budget.

## Measurements

Provider `total_tokens` includes input and output, including reported reasoning
tokens. Cached input remains part of the token count. Each run's business and
observer usage are accounted for separately. Failed requests without recorded
usage are listed separately; their unreported token consumption is unknown.

| Condition | Business tokens | Observer tokens | Total | Task result | Capture |
| --- | ---: | ---: | ---: | --- | --- |
| Baseline | 2,222 | 0 | 2,222 | Passed | Disabled |
| AgentSight, first capture | 2,505 | 6,897 | 9,402 | Passed | Tail incomplete |
| AgentSight, capture retry | 3,237 | 5,143 | 8,380 | Passed | 4 requests and 4 responses |
| AgentSentinel | 2,884 | 55,917 | 58,801 | Passed | Native tracer and online audit |

The first AgentSight run retained only two complete HTTP pairs from three model
requests because the consumer exited before the producer's buffered tail drained.
Its observer also reached the upstream 4,000-output-token limit. Both records are
retained. The capture retry retained eight HTTP records with bodies and 512 system
events, occupying 133,261 bytes. The upstream correlator produced four groups,
all classified as temporal-proximity correlations.

For the complete capture, the independent semantic analysis consumed 5,143 tokens
in addition to 3,237 business tokens. That is 159% extra relative to that run's
business tokens. Task trajectories varied across the independent runs. Compilation
and capture debugging overlapped parts of the experiment; elapsed times are
recorded as diagnostics. AgentSentinel runs inside its required Docker container;
the other two conditions use guest-host workspaces with the same input and result
check. Workspace paths therefore differ across conditions.

AgentSentinel made three context-summary requests and fifteen successful security
requests. Nine security requests returned HTTP 502 without recorded usage; SDK
retries are included in the request ledger. Two audit queries reached the upstream
timeout. The original error path resumed the intercepted process. The monitor
recorded 118 cache-hit messages. The business run completed in 446.57 seconds.

| Additional analysis | Successful requests | Input tokens | Output tokens | Reasoning tokens within output | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| AgentSight, complete capture | 1 | 2,866 | 2,277 | 1,405 | 5,143 |
| AgentSentinel, context summary | 3 | 3,564 | 460 | 240 | 4,024 |
| AgentSentinel, security review | 15 | 20,167 | 31,726 | 28,961 | 51,893 |

Both implementations exercised an independent analysis path. AgentSight analyzed
the captured trace after execution. AgentSentinel summarized tool context and
intercepted system operations for repeated online review, with rules and caches
handling other operations. In this run, repeated analysis input and model reasoning
output both contributed substantially to the additional tokens. These measurements
describe the retained upstream defaults with the selected model and gateway.

## Evidence

Raw artifacts are stored under `results/external-agent-audit-20261030/`:

- `environment.json`: kernel, model, and source revisions.
- `summary.json`: per-run business usage and gateway totals including retries.
- `gateway-requests.jsonl`: request roles, status, usage, and elapsed time.
- `runs/`: business trajectories, tool results, native traces, correlation output,
  observer prompt and response, and startup-failure records.
- `sentinel-adapted/`: the source files changed for local compatibility.
- `sentinel-compatibility.patch`: the diff against the pinned upstream source.
- `harness/`: the local task harness and reproduction scripts.
- `build-logs/`: original build output.

Legacy GPT-4o-mini connection checks are retained separately under
`runs/legacy-gpt-4o-mini/`.

The repository also includes the
[measurement summary](external-agent-audit-results-20261030.json).
