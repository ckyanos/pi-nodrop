# Native Pi five-condition Terminal-Bench comparison

The experiment uses Harbor 0.25.0, native Pi 1.4.0, and DeepSeek V4.1 Flash (1017) through iBrain. Each condition executes each of the three original tasks once. The request credential is `project-ak-api`.

These are the October 30 results with the original 900-second agent deadline. The current runner uses independent task copies with no agent execution deadline. It preserves task instructions, verifier files and resource settings and records the configuration change and file hashes in each new protocol. Unlimited-duration runs will be stored separately.

## Task results and tokens

Token counts include provider-reported input, cached input, output, and reasoning within output. Business usage is reconciled across Harbor, native Pi sessions, and the gateway. Independent analysis is accounted for separately. Requests without reported usage have unknown additional consumption.

| Condition | Verifier passed | Pi completed normally | Business tokens | Independent analysis tokens | Reported total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 3/3 | 3/3 | 102,946 | 0 | 102,946 |
| AgentSight + semantic analysis | 3/3 | 3/3 | 200,598 | 17,213 | 217,811 |
| AgentSentinel | 2/3 | 0/3 | 72,976 | 792,905 | 865,881 |
| NoDrop, fixed raw | 3/3 | 3/3 | 121,311 | 0 | 121,311 |
| NoDrop, agent-selected policy | 3/3 | 3/3 | 146,847 | 0 | 146,847 |

All three AgentSentinel trials reached the original 900-second agent timeout. The certificate and Git artifacts passed their verifiers; the log task failed. The normal-completion column records that distinction.

| Task | Baseline | AgentSight | AgentSentinel | NoDrop, fixed raw | NoDrop, agent-selected |
| --- | ---: | ---: | ---: | ---: | ---: |
| openssl-selfsigned-cert | 14,844 | 66,315 | 334,321 | 18,437 | 20,800 |
| log-summary-date-ranges | 38,827 | 94,680 | 323,150 | 66,855 | 46,718 |
| fix-git | 49,275 | 56,816 | 208,410 | 36,019 | 79,329 |

| Independent analysis role | Requests | Requests with usage | Input tokens | Output tokens | Reasoning within output | Reported total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AgentSight + semantic analysis / observer | 3 | 3 | 8,789 | 8,424 | 6,019 | 17,213 |
| AgentSentinel / sentinel-context | 15 | 15 | 29,959 | 2,497 | 1,168 | 32,456 |
| AgentSentinel / sentinel-security | 188 | 188 | 330,799 | 429,650 | 407,656 | 760,449 |

Each table cell is an independent trajectory. Different commands, tool outputs, and model response counts affect business tokens. Differences between the column totals include that variation. The independent-analysis column identifies measured extra model work directly. Original task verifiers measure task completion; security-detection accuracy requires a separate attack evaluation.

Some AgentSentinel security responses consume the full default 4,096-token output allowance in reasoning and return empty `choices` through iBrain. The gateway converts such responses to HTTP 502; SDK retry and timeout behavior is retained, and provider-reported tokens for these attempts are counted. This is a model/response-limit compatibility factor in the selected configuration. Per-role counts appear in `reasoning_only_empty_choices_requests`; error and finish-reason counts are retained.

## Shared execution protocol

- Terminal-Bench revision: `7131e4375048a0e408a8fb404b5f499d726b695b`. Original task files, verifier, user, working directory, resources, and 900-second agent timeout are retained.
- All conditions delegate to upstream `Pi.run` and retain the original `read`, `bash`, `edit`, and `write` business tools and native outputs.
- Business reasoning effort is `medium`, with the existing 2,048-token response configuration. There is no additional cumulative token, turn, or tool-call budget. Automatic business-request and whole-trial retries are disabled.
- The shared TLS gateway forwards business prompts and tool schemas and records provider usage by request role. The actual credential remains in the gateway process; agent-side captured traffic uses a local transport credential.
- Baseline uses the official installer. Subsequent task containers receive independent copies of that installation, verified using the archive, Node executable, Pi CLI SHA-256, and Pi version. Installation time is separate from agent execution.
- The VM uses Linux 6.8.0-137-generic, four virtual CPUs, 4 GiB of memory, and QEMU TCG. This run evaluates tokens and task outcomes; it does not establish native-hardware CPU overhead.

## Monitor mechanisms and compatibility adaptations

[AgentSight](https://github.com/eunomia-bpf/agentsight/tree/892ee9c2c33e492506444aefe67adf95960c7316) uses its paper-era implementation. Its native eBPF collector records process events, and its native SSL uprobes attach to the Pi Node executable, which embeds OpenSSL. A Pi lifecycle hook supplies the PID and waits for probe readiness. Semantic content comes from captured TLS traffic. HTTP/SSE reassembly converts the records into the format expected by the original correlation script and semantic analyzer. The original analyzer prompt, 20-entry sample limit, and 4,000-token output limit are retained; real analysis runs after the task, and mock fallback is disabled.

[AgentSentinel](https://github.com/m4p1e/agent-sentinel/tree/c3e25e6678c4c77cfba74c91bcda306567b1defd) receives user, assistant, tool-call, and tool-result context through its original A2M protocol from Pi lifecycle hooks. The original Go monitor, native eBPF/BPF-LSM tracing and enforcement, context summarizer, security auditor, rules, and caches run online. Its OpenAI transport is routed to the same DeepSeek model. Defaults remain `process-trace-level=0`, `binary-level-cache=false`, `tool-use-timeout=60`, `EventCountLimit=20`, and a 4,096-token auditor response limit.

AgentSentinel compatibility changes resolve the current container cgroup and Bash executable through the container host PID, regenerate BPF objects for the kernel BTF, use the Linux 6.8 inode ctime field, and return `-EPERM` for task-kill denial. A short symlink alias keeps the original Unix socket within the Linux path limit. The native binary is unchanged by the alias launcher. The Pi adapter validates the upstream handshake and exits before model execution if connection fails. A real native-Pi RPC preflight verified connection and passive tracing without model requests.

AgentSight capture and deterministic correlation can also run by themselves. This selected condition explicitly enables the separate upstream semantic-analysis script. AgentSentinel includes online security assessment, while NoDrop produces audit records with executor-supplied identity and retention configuration. The measured functions differ; security judgments are an additional analysis stage relative to the NoDrop audit path.

NoDrop receives the tool-call identity directly from the executor. The fixed-raw condition submits a fixed policy; the control-plane condition receives `audit_policy` in the original tool JSON, validates it, and applies it before tool execution. Saved audit records remain separate from business-model context. These conditions invoke no independent audit model.

## Initial input and execution paths

| Task | Baseline input | AgentSight input | AgentSentinel input | Fixed-raw input | Agent-selected input |
| --- | ---: | ---: | ---: | ---: | ---: |
| openssl-selfsigned-cert | 1,898 | 1,898 | 1,898 | 1,898 | 2,054 |
| log-summary-date-ranges | 1,956 | 1,956 | 1,956 | 1,956 | 2,112 |
| fix-git | 1,614 | 1,614 | 1,614 | 1,614 | 1,773 |

| Condition | Business model responses | Model tool calls | Tool-result text characters |
| --- | ---: | ---: | ---: |
| Baseline | 20 | 20 | 26,974 |
| AgentSight + semantic analysis | 27 | 26 | 66,094 |
| AgentSentinel | 16 | 18 | 27,201 |
| NoDrop, fixed raw | 18 | 18 | 63,694 |
| NoDrop, agent-selected policy | 24 | 27 | 33,202 |

## Audit evidence

AgentSight records and reconstructed HTTP pairs are checked against actual business requests. AgentSentinel connection, passive tracing, tool notifications, native events, cache activity, and separate analysis roles are recorded. NoDrop retained references and policies are checked against tool-call metadata. These collectors retain different event types and representations, so event counts are not equivalent coverage measures.

The original AgentSight process collector uses substring matching when seeding its process list. Its `pi` filter also includes initial metadata for the `pi-audit-gw` transport process. Those records remain in the original capture and analysis; per-case counts are disclosed in `capture.gateway_process_records`. SSL capture is restricted to the Pi PID and excludes gateway upstream traffic.

| AgentSight task | System records | HTTP pairs | Truncated SSL records | Pending requests | Gateway metadata records |
| --- | ---: | ---: | ---: | ---: | ---: |
| openssl-selfsigned-cert | 590 | 12 | 0 | 0 | 2 |
| log-summary-date-ranges | 345 | 5 | 0 | 0 | 2 |
| fix-git | 815 | 10 | 0 | 0 | 4 |

AgentSentinel security queries in the certificate run include Python first-import bytecode writes under `__pycache__`. In the log task, one Bash invocation loops over log files and executes `grep` with different file arguments, producing repeated execution reviews under the retained `binary-level-cache=false` default. The per-task counts below identify these sources. Security-operation descriptions are also checked for adapter bookkeeping paths.

| AgentSentinel task | Tool notifications | Native security operations | Pycache-path queries | Grep execution queries | Cache hits | Adapter-path security queries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| openssl-selfsigned-cert | 6 | 46 | 3 | 0 | 230 | 0 |
| log-summary-date-ranges | 3 | 64 | 0 | 50 | 326 | 0 |
| fix-git | 9 | 48 | 0 | 0 | 75187 | 0 |

| NoDrop condition / task | Raw events | Count rows | Events represented by counts | Audit bytes | Policy calls | Missing-policy rejections |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| NoDrop, fixed raw / openssl-selfsigned-cert | 7,705 | 0 | 0 | 583,931 | {"raw": 5} | 0 |
| NoDrop, agent-selected policy / openssl-selfsigned-cert | 0 | 676 | 8,464 | 113,464 | {"counts": 6} | 0 |
| NoDrop, fixed raw / log-summary-date-ranges | 8,909 | 0 | 0 | 749,711 | {"raw": 3} | 0 |
| NoDrop, agent-selected policy / log-summary-date-ranges | 0 | 25,740 | 179,991 | 4,264,075 | {"counts": 4} | 0 |
| NoDrop, fixed raw / fix-git | 10,478 | 0 | 0 | 783,005 | {"raw": 10} | 0 |
| NoDrop, agent-selected policy / fix-git | 171 | 1,480 | 18,484 | 256,337 | {"counts": 16, "raw": 1} | 0 |

## Retained integration attempts

Before the corrected AgentSentinel run, the new Pi adapter incorrectly expected the handshake to echo the request. The upstream server returns a different constant. This integration failure produced 20 business requests and 68,716 reported tokens, with no active independent review; it is retained separately from the valid comparison. The failed attempt is not a measured AgentSentinel audit result.

Zero-model setup failures include an unsupported Harbor option, an overly broad AgentSight startup-log check, and the Unix socket path limit. Their original artifacts are retained. A guest became unresponsive after the failed Sentinel attempt; persisted logs did not establish the cause. Subsequent NoDrop log and Git cells each use a fresh kernel boot and retain the module until VM restart. Completed model executions are preserved.

Additional attempts, including any requests without usage, are summarized in `additional_attempt_usage` in the structured result.

## Artifacts and reproduction

- [Structured results](fiveway-comparison-results-20261030.json)
- [Experiment configuration](../experiments/fiveway-comparison.json)
- [Official Harbor runner](../scripts/run_fiveway_comparison.py)
- [External monitor adapter](../scripts/harbor_external_audit.py)
- [Pi A2M integration](../src/sentinel-extension.mjs)
- [Usage and evidence summarizer](../scripts/summarize_fiveway_comparison.py)

Raw evidence is under `results/harbor-fiveway-20261030/`: per-task Harbor results and Pi sessions, role-specific request ledger, monitor captures, observer responses, NoDrop audit files, compatibility sources, protocol hashes, installation manifest, connection preflight, and retained setup/integration attempts.
