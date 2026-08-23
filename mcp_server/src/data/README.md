# src/data/

Runtime state shared across capabilities - not tied to any single one,
so it doesn't live inside a `capabilities/<name>/` folder. Gitignored
except for this README.

- **`pending_requests.db`** - `infra/pending_requests.py`'s SQLite store
  for approval-gated / resumable requests (`infra/approvals.py`). Any
  capability that registers a `GatedCapability` uses this same file;
  none of them own it individually.

A capability that owns runtime state outright - state nothing else ever
reads or writes - keeps it in its own `capabilities/<name>/data/`
instead. `capabilities/otp/README.md` is the example: `otp.db` is
created there, not here, because only the `otp` capability ever touches
it.
