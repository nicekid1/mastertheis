# Accounts and storage — rollout status

Update: an optional rootless per-job analysis path is now implemented; see
[isolated-analysis.md](isolated-analysis.md) for activation requirements and
limitations. The warnings below still apply to the legacy in-process agent and
to deployments without the isolated runtime. The text-chat endpoint is separate.

This change introduces authentication, administrator/user roles, private HTTP workspaces and upload quotas. **It does not yet make the Python agent a safe multi-tenant execution service.** Ordinary users can upload/manage/view data but cannot start agent runs, invoke direct geoprocessing, rejoin/cancel admin runs, or attach server-side files. These operations fail closed at the server, not just in the UI. Administrators remain fully trusted and retain the existing in-process agent.

Do not expose this version as a public, untrusted multi-user GIS analysis service. The next required stage is an isolated worker per run/user, filesystem and process/network limits, output quota enforcement, and explicit ownership on run streams. Turning off the checks is not a substitute for isolation. File parsers also run in the web process today and require isolation/resource limits before accepting hostile public uploads.

## Initial administrator

There is no default password or public bootstrap endpoint. Rebuild the image, then create the first administrator interactively:

```sh
docker compose up -d --build gisclaw
docker compose exec gisclaw python -m app.auth create-admin --workspace /workspace
```

The command asks for a username and nonempty password; the old 12-character minimum has been removed. The 256-character upper limit remains. Short passwords are accepted, but strong passwords are still recommended. The password is not echoed or placed in shell history. Locally, use `python -m app.auth create-admin --workspace /absolute/workspace/path` with the same workspace as the server. The CLI can create a recovery admin if all credentials are lost. Do not run it against the source directory accidentally.

Public registration is explicitly disabled: `/api/auth/register` and `/api/auth/signup` return 403, and the login page contains no registration form. Account creation is administrator-only (apart from the trusted local bootstrap CLI).

Administrators can change an ordinary user's storage allowance under **Account → Users & files → Storage quota**, in MiB. The server stores whole bytes (`quota` on the admin PATCH endpoint). Zero disables uploads. Reducing the limit below existing usage retains files and permits viewing/deletion; further writes are blocked until sufficient space becomes available. Increases take effect on the next upload without requiring the user to sign in again. Quota edits and uploads share a per-user lock so requests queued during a change reload the new allowance.

The total storage quota is separate from the per-request upload limit: ordinary-user uploads are still capped at 50 MiB per request to bound server memory, even when the administrator grants a larger total allowance.

Sign in, open **Account → Users & files** to create accounts, disable/re-enable users, reset passwords, inspect/download/delete files. File deletion asks for confirmation and is permanent. Disabling accounts does not delete their data. Password changes and disabling a user revoke their sessions. Role changes on existing accounts are intentionally not supported; creating an administrator is an explicit operation.

## Storage and migration

- Existing projects and global settings stay where they are, accessible to trusted administrators. Nothing is moved or assigned to users automatically.
- User data lives in `<workspace>/.users/<random-user-id>/`. Request-local context selects the root; ordinary users cannot choose another user's root.
- Each ordinary user receives **50 MiB (52,428,800 bytes)**. All files in the workspace, including documents, archives, hidden files and metadata, count toward displayed usage. A 64 KiB reserve covers metadata writes. Metadata requests are capped at 16 KiB; uploads are refused before writing if the remaining budget is insufficient. Replacement uploads are charged conservatively against the full incoming size, not just their size increase.
- This is an application upload quota, not an OS filesystem quota. No generated-output guarantee is claimed: analysis for ordinary users remains disabled. Administrators are not quota-limited. An administrator/host process can place files over a user's quota externally; subsequent writes are refused but existing data is not silently deleted.
- Mutations are serialized per user within the ASGI process. **Run one web worker**, as in the supplied Docker command. Multi-process deployments need shared transactional reservations/filesystem quotas before being supported.
- The account database lives in `.gisclaw/accounts.sqlite3` (mode 0600). Back up it and `.users/` along with existing project data. Preserve private permissions on backups.

## Security controls and limits

Passwords use salted `hashlib.scrypt`; opaque random session tokens are stored only as SHA-256 digests. Cookies are HttpOnly, SameSite=Strict, expire after 12 hours, and become Secure for HTTPS requests or `GISCLAW_SECURE_COOKIES=1`. Login attempts are limited to 10 per source address per 15 minutes; successful login clears the counter. CSRF protections require the app header and same-origin requests for mutations. APIs require a session; administrative endpoints additionally require the admin role. API responses are no-store; file responses have restrictive CSP and nosniff headers.

Keep the default loopback Docker binding during development. For organizational deployment use HTTPS through a correctly configured trusted reverse proxy, set `GISCLAW_SECURE_COOKIES=1`, protect the workspace from other OS users, and add proxy request/rate limits. Do not trust forwarded headers from arbitrary clients. Sessions/passwords must never be transported over unencrypted remote HTTP. MFA, email verification/recovery, self-registration and security audit logging are not implemented in this version; account creation/recovery is administrator-operated.

## Token allowance

Each account (including administrator accounts) starts with a persistent **10,000-token lifetime allowance**, shared across models, projects, requests and provider connection tests. It is not per day or per run. Old accounts acquire the same default without resetting existing account data. `Account` shows confirmed usage, reserved/unconfirmed usage and remaining allowance. There is no client-controlled budget/reset parameter.

`app/token_budget.py` reserves input + maximum output atomically in SQLite before each engine call. The input admission estimate is deliberately conservative (UTF-8 bytes plus a framing allowance), not an exact tokenizer for every provider. Long system prompts/history may be rejected even if a tokenizer would count fewer tokens. The output request is capped to the remainder; the reasoning-model default must not increase an explicitly supplied cap. All calls on the run's engine, including intent routing, summaries and log compaction, share this meter. SDK automatic retries are disabled for metered engines. The server derives account ownership from the authenticated session.

Reported prompt and completion tokens settle the reservation, including cached input and reasoning/output usage. OpenAI-compatible prompt totals already include cache reads; Anthropic input/cache-read/cache-write fields are summed once. See the [official Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) for `max_completion_tokens`, which includes visible and reasoning output.

Timeouts, failures, missing usage and process crashes leave reservations charged conservatively; they are **not silently refunded**. New calls cannot reserve more than the remaining balance. Final provider usage is recorded honestly even if a noncompliant/custom provider reports more than the reservation. Exact external billing cannot be guaranteed for arbitrary providers that ignore output limits or insert hidden input: validate provider behavior before enabling them for metered accounts. This is tested with fake providers, not certified against live providers.

The pre-existing user execution-isolation restriction remains: this change does not enable ordinary-user Python/agent runs. It adds the persistent accounting and meters enabled administrator runs/provider tests now; ordinary-user execution must keep the same account-bound meter when an isolated worker is introduced.

## Verification

`tests/test_accounts.py` exercises password hashes, session revocation, throttling, unauthenticated access, role restrictions, two-user project/file/preference isolation, concurrent quota enforcement, hidden-file accounting, symlink traversal and administrator file visibility. The existing API fixture now signs in as a temporary administrator (no authentication bypass). Run `python -m pytest -q tests --ignore=tests/test_ui.py` with the project's runtime and test dependencies. Browser UI verification is separate.
# Temporary token test mode

The current deployment uses GIS-only conversation:
`GISCLAW_TEXT_CHAT_ENABLED=0` and `GISCLAW_TOKEN_BUDGET_ENABLED=0`.
The separate `/api/chat` endpoint returns 403 `text_chat_disabled` for authenticated
users, including admins, without initializing a model. Account capabilities report
`chat_enabled=false`, the UI defaults to GIS and hides the text-mode selector.
Project selection and a ready isolated worker remain required for ordinary users.
Text-only chat can later be restored with `GISCLAW_TEXT_CHAT_ENABLED=1` and an app
restart; its implementation is retained. This does not enable legacy non-isolated
execution for ordinary users, nor disable storage/security/provider limits.

Set `GISCLAW_TOKEN_BUDGET_ENABLED=0` in `.env` and recreate the app container
to bypass account token accounting, reservations and quota checks for all users.
For direct development launches, export the variable in the server's environment.
The account screen explicitly shows test mode instead of a misleading balance.
Existing token records remain untouched. Restore `=1` and restart/recreate to
resume accounting against the existing history; test-period usage is not backfilled.
The default when the variable is absent is enabled. This is a server-only setting,
not a user-controlled API parameter. Provider charges, per-response output limits,
authentication, storage quotas and worker resource/isolation limits still apply.

# Text-only chat and isolated analysis rollout

`POST /api/chat` is available to authenticated users, independently of
`POST /api/run`. It accepts a question and bounded text history, uses only an
enabled/ready administrator-configured model, and meters the authenticated
account's lifetime token budget. It never instantiates the GIS agent or sandbox,
loads project files, or injects global memory/skills. Model output is displayed
as text, not dispatched as tool calls. Only one provider call per account is
allowed at a time in the supported single-worker deployment. Disconnecting does
not refund usage or free the slot before that call completes.

The UI explicitly selects text chat versus GIS analysis. Text history is held
in the browser view only, not persisted; refreshing or switching projects clears
it. Storage quotas are unaffected by this endpoint because it writes no project
files. Token accounting still writes to the central accounts database.

**GIS analysis for ordinary users is still disabled.** This change is not an
isolated execution implementation. Enabling it requires a separately deployed
execution service, not exposing the Docker socket to the web app. Before rollout:

- Select a dedicated/rootless execution host and authenticated service boundary.
- Run each job without API keys, account database, host mounts or network access;
  supply only a snapshot of the authorized user's selected project files.
- Enforce read-only runtime, unprivileged user, CPU/memory/process/time/output
  limits, and validate returned regular files (reject links and traversal).
- Keep LLM calls and token reservations in the trusted application; give workers
  code/data only. Check remaining storage before accepting outputs.
- Bind every job, event stream, cancel request and artifact to its owning user;
  test cross-user access, filesystem escapes, resource abuse and interrupted jobs.

Do not remove the existing non-admin `/api/run`/`geoprocess` denial before these
controls exist and have been tested. The current admin sandbox is not a tenant
security boundary.
