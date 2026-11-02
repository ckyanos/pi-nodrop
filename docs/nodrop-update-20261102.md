# NoDrop upstream update

The vendored baseline tracks [PKU-ASAL/NoDrop](https://github.com/PKU-ASAL/NoDrop)
at `dev` commit `f80c9a82c162aa58cb3344b8078f6211d52cdf58`
(`update for stable version`, 2026-11-02).

The upstream checkout is clean. `vendor/nodrop-baseline.patch` is therefore
empty; `vendor/nodrop-provenance.json` identifies the commit and hashes all 77
baseline files. Applying `vendor/pi-nodrop.patch` to this baseline reproduces
all 80 vendored files byte for byte.

The integration retains executor-supplied call identity, fork inheritance,
per-call raw/counts retention, explicit buffer flushing, configurable audit UID,
and the configurable ioctl path used by containers. The monitor adopts the
upstream TLS restoration on repeated entry. The startup merge preserves
`PI_NODROP_IOCTL_PATH` while incorporating that upstream change.

The statistics interface follows upstream: `n_evts`, `drop_evts`, and
`drop_unsolved`. The previous baseline's additional `drop_overflow` and
`monitor_entries` diagnostics are removed. Historical experiment reports retain
their original source versions and statistics.

## Validation

An isolated Linux `6.8.0-137-generic` checkout built the kernel module, monitor,
control utility, and Node N-API binding. All eight selected protocol tests passed.
The tests used scripted model responses and made no model API requests.

The native integration smoke test failed: the edit operation left the original
file content unchanged, and the kernel reported `scheduling while atomic` on
the `syscall_exit_probe` → `nod_load_monitor` path. The test exited and unloaded
the module. The subsequent native scope checks did not run. Runtime compatibility
with this updated baseline remains unresolved; the earlier working runtime and
historical benchmark results are preserved.
