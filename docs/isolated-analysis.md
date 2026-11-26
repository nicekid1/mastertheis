# Isolated GIS execution

The optional `/api/projects/{pid}/analysis` path runs the existing GIS ReAct agent
in a disposable container. LLM calls remain in the trusted API process and are
charged to the authenticated account. The worker receives no credentials or
account database, no host mounts and no network. Its filesystem is read-only
except a 256 MiB temporary filesystem; it runs as UID 65534, with all capabilities
dropped, no-new-privileges, 1 CPU, 1 GiB memory, 64 processes and a five-minute
deadline. Each job has at most 12 agent rounds / 16 model RPC messages.
Only one isolated container job is admitted at a time in this API process.

For testing, the coordinator's former 32,000-character rejection of combined
system/user model messages is disabled. String-type validation, bounded RPC
frames and worker resource limits remain. This does not remove provider context
limits or billing; longer prompts may increase provider costs and latency.

Conversational GIS answers (greetings, explanations and clarification questions)
use the opt-in `respond(summary)` terminal action without requiring an output
file. File-producing tasks continue to use `finish(summary)` with the existing
output guard/validation. Both terminal paths preserve the full final answer for
the chat UI. This does not enable the separate `/api/chat` text-chat feature.

Inputs snapshot all files in the requesting project's `data/` plus only output
layers explicitly selected on the map (including shapefile companions), maximum
50 MiB combined. Unselected historical outputs are not recopied or counted;
this prevents a large previous result from blocking every future request.
To analyze a previous output, select it on the map or upload it as source data.
The cap still applies to required inputs and is independent of token accounting
and account storage quotas. No project files are deleted by snapshot preparation.
Selected-feature preparation runs inside the worker. Returned files are decoded
as regular files, path-validated and size-checked before an atomic directory
commit to `outputs/analysis-<random-id>/`. The user's mutation lock is held until
commit, including after a browser disconnect. Token reservations still apply.
The API does not trust a worker-reported filesystem path or token count.

## Deployment prerequisite

### Rootless Compose deployment (configured on this workstation)

`docker-compose.rootless.yml` runs the trusted coordinator inside the dedicated
rootless daemon and mounts **only that rootless socket** into the coordinator.
The socket is a privileged capability within the host user's account; do not
share this daemon with unrelated workloads. Generated-code workers never receive
this socket, workspace mounts, API keys or credentials. This alternative avoids
installing the native GIS stack on the host. Never substitute the system/rootful
socket, and never enable `privileged` mode.

The runtime base is initially seeded from the previously installed GIS image.
Subsequent code updates:

```sh
docker --context rootless build --network none -f Dockerfile.rootless -t gisclaw:isolated .
docker --context rootless compose -f docker-compose.rootless.yml up -d
```

Keep `GISCLAW_DATA` pointing to the existing host data directory. The socket
defaults to `/run/user/1000/docker.sock`; override `GISCLAW_ROOTLESS_SOCKET` for
another account. Do not run old/rootful and new/rootless APIs against that data
directory simultaneously. The rootful container can remain **stopped** for rollback.
After a successful switch, disable its restart policy to avoid a port clash.
For startup before login and persistence after logout, enable user lingering:
`sudo loginctl enable-linger nicekid` (replace the account as appropriate).

### Alternative native API deployment

The default Compose deployment does **not** enable this feature. Do not mount
`/var/run/docker.sock` into it and do not enable privileged mode. Run the trusted
API natively under a dedicated unprivileged Linux account with a dedicated
rootless Docker daemon (not one managing unrelated containers). A dedicated
execution VM is preferable for public deployments. Rootless Docker, cgroup v2,
memory/PID limits and the default seccomp profile are checked before advertising
the feature. OS/rootless setup requires administrator approval and is not
performed by the application.

After provisioning that environment, build the current worker image in that
rootless daemon, install the API's normal GIS dependencies, and configure:

```sh
docker build -t gisclaw:isolated .
export GISCLAW_ISOLATED_ANALYSIS=1
export GISCLAW_WORKER_IMAGE=gisclaw:isolated
# Set GISCLAW_WORKSPACE to the intended existing data directory explicitly.
uvicorn app.server:app --host 127.0.0.1 --port 8765 --workers 1
```

Restart the API after changing runtime configuration; runtime readiness is
rechecked every five seconds so a temporary Docker outage does not disable
analysis permanently.
Do not run this native API and the old Compose API against the same workspace
simultaneously. The current lock design supports one API worker only.

When available, the UI routes GIS analysis through the isolated endpoint for
both roles. The legacy non-admin `/api/run` and direct geoprocess routes remain
denied: they are not isolation boundaries. Without a qualified runtime, ordinary
users retain text chat and receive a clear unavailable status for analysis.

## Limitations

This is a bounded request/response analysis path, not the old SSE run registry.
Disconnect/Stop detaches the browser but the bounded job can finish and commit
outputs; it does not refund provider usage. Analysis conversations are currently
not persisted by this path. Outputs are saved and visible in the file tree.
Only data/outputs are supplied, not arbitrary host paths, documents or API keys.
Image trust, kernel/container runtime patching, rootless host provisioning and
public-deployment security review remain operator responsibilities. Rootless
containers are not equivalent to separate virtual machines.

The analysis panel receives executed code and tool summaries after the isolated
request finishes. If a later model call fails, completed tool summaries are
included in the error response and shown in the panel. These reports are held in
the browser session and are not persisted across reloads. A waiting status is
shown while the request is in progress; this endpoint does not stream reports.
Provider HTTP status codes are surfaced for common upstream errors when the SDK
provides a status. This identifies authentication, billing and rate-limit
responses without exposing provider response bodies or credentials.
