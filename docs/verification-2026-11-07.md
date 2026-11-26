# Verification — 2026-11-07

## Analysis report and provider diagnostics — 2026-11-21

The isolated analysis response now includes executed code and allowlisted tool
summaries. Completed steps are also returned when a later model call fails, so
the Analysis/code panel can show partial work alongside the error. The UI shows
a waiting state while the request is running; reports arrive when it finishes
and are not persisted after reload. The run state now reports failure instead
of appearing idle when a GIS request fails.

The configured provider remains `api.gapgpt.app`; no model, key or provider was
changed. SDK HTTP status is now preserved through the error handling path and
common upstream statuses receive specific Persian explanations. Existing tests
passed: 19 backend checks across provider classification, worker protocol,
HTTP/rootless analysis and synthetic land-use GIS; all four frontend test files
and the production build passed. The local production service was recreated
with image `sha256:a1f8d77efcdec89259e7f73b970761ec61f0dec5e7da9341beec22adb4a7069a`.
Live health returned HTTP 200, isolated execution was available, the effective
model timeout was 180 seconds and internal token accounting was disabled.
Previous image is retained as `shahrkav:before-analysis-report` for rollback.

Recent historical failures for reference `f3ed45601818` occurred around 109
seconds after model initialization. The previous build logged only the exception
type, so the provider's HTTP status for that request cannot be recovered. Other
recent calls in the current logs failed within 0.5–7 seconds, consistent with an
upstream request rejection rather than a long GIS execution. A fresh live model
request using synthetic data was not completed because the execution approval
service rejected it after the usage limit was reached. Therefore the UI/report
path and deployment are verified, but a successful live response from the
provider and the user's original land-use task remain unverified.

## GIS-only deployment — 2026-11-20 (latest)

At the user's request, separate text chat is now disabled both server-side and
in the UI. GIS conversation is the default. Token accounting remains disabled.
`GISCLAW_TEXT_CHAT_ENABLED=0` and `GISCLAW_TOKEN_BUDGET_ENABLED=0` are active.
No storage quotas, authentication or worker isolation checks were removed.

Verified: 10 offline feature/token tests, all 3 frontend test files, production
frontend build, 8 HTTP analysis tests and 1 storage regression. The GIS-only
HTTP scenario rejects text chat for both admin and ordinary users before model
initialization, preserves anonymous 401, and produces real GIS buffer output
for an ordinary account with a zero token quota without writing token records.
Provider responses in these tests are scripted; no paid model request was made.

Deployed image:
`sha256:3c242dd139e9584988fbe8d1f1af4e40aedea52357324edaa47ba41397767839`.
Live checks: text chat false, token accounting false, isolated worker ready,
and both active accounts report GIS enabled. Served `index-CxQ9Bpip.js` matches
the build. Previous image retained as `shahrkav:before-gis-only`. This scoped
change does not resolve the previously reported direct-Claude SDK compatibility
issue or legacy quota-test expectation mismatch below.

## Follow-up full verification — 2026-11-20

Tested the running Shahrkav image
`sha256:a81d4ea60964a1e6494d09fdc5fb0859565d9a1708e662d513fb043c3af768f6`
using a disposable coordinator without production workspace mounts or real keys.
Production was not restarted or replaced. Its token metering is **disabled** and
isolated-worker readiness is **true**. This supersedes historical deployment
status below, including the earlier pending test-mode approval.

### Passed

- Frontend: all 3 test files (`api`, `brand`, `runEligibility`); production build.
- Live HTTP: homepage 200 with the Shahrkav title; favicon, CSS and JS all return
  200 and their bytes match the local build. Anonymous account/project/admin
  requests return 401.
- Full non-browser pytest suite: **75 passed, 5 failed** (54 subtests passed).
  Includes accounts, login, admin-only registration/user management, tenant
  boundaries, files, basemaps, local fake-model server, selection and urban tools.
- Separate isolated-analysis HTTP suite: **8 passed**, including real GIS output,
  selected-feature isolation, disabled-accounting mode with zero quota, timeout
  error codes and output retrieval. Model replies were scripted.
- Storage HTTP regression: **1 passed**; parallel/chunked uploads, existing-file
  preservation, documents, archived/hidden files and output quotas.
- Offline token test-mode/reconciliation suites: **8 passed**.
- Real worker security/GIS regression: **1 passed** (no host mounts, credentials,
  Docker socket or network; unprivileged execution and valid buffer output).
- Urban/DBF standalone run: **21 passed** (also included in the full pytest suite,
  not additional unique tests).
- Offline Docker build succeeded with `Dockerfile.rootless`, `--pull=false` and
  `--network none`, using the existing local runtime. Test image retained as
  `shahrkav:verification`; live image was not retagged.
- Python compilation and `git diff --check` passed.

### Findings requiring follow-up

1. **Direct Claude SDK compatibility:** `ClaudeEngine.generate` sends
   `temperature` for model names outside its sampling-exclusion list, but the
   installed Anthropic `Messages.create` signature does not accept it. Reproduced
   `unexpected keyword argument 'temperature'` before any HTTP call. An excluded
   model name exercised the mocked HTTP timeout exactly once and correctly
   returned `model_timeout`. OpenAI transport timeout/no-retry checks passed.
   The 3-test transport suite has 2 passing tests and 1 failing parameterized test
   (Claude subcase). No production-code fix was applied during this test request.
2. **Quota test/default mismatch:** all 5 pytest failures trace to the locally
   configured default `TOKEN_LIMIT=100000` versus tests expecting 10000. In a
   separate temporary process, overriding that constant to 10000 made all 10
   token/account diagnostic tests pass. This diagnostic did not edit source or
   live settings. Accounting remains disabled in production as requested.

The transport test harness itself was corrected to support the installed
`httpx2` SDK transport as well as legacy `httpx`; its old private-attribute
assumption prevented it from reaching the real Claude defect.

### Not verified

- Visual/browser interaction: Browser discovery returned no available browsers;
  browser tests were not run. Static and HTTP checks are not visual QA.
- Live external LLM availability, billing and response latency: no paid provider
  requests were made. Successful scripted/fake-server tests do not prove live
  provider connectivity or model output quality.

Test dependencies (`pytest`, `httpx`) were installed only in the disposable
coordinator. Real accounts, project files and provider settings were untouched.

---

Scope: Run-button eligibility, text chat, isolated GIS analysis, tenant/storage
boundaries, token accounting and result retrieval. All execution tests used
temporary accounts/files and scripted model responses; no live model was billed.

## Passed

- `npm test`: both frontend test files passed (HTTP error details, stream decoding,
  localization and run eligibility).
- `npm run build`: production bundle built successfully.
- `python -m unittest tests.test_urban_ops tests.test_dbf -v`: 21 tests passed,
  covering urban operation catalog/tool execution and Persian DBF previews.
- `python tests/storage_regression.py`: HTTP storage/chat regression passed,
  including parallel/chunked uploads, hidden and archived files, quota resizing,
  token exhaustion, malicious output paths and excess output storage.
- `python tests/analysis_regression.py`: 7 tests passed, including real rootless
  workers. Authenticated user upload -> selected-feature snapshot -> operation
  help -> load vector -> buffer -> output retrieval; verified one selected
  feature and approximately 31,000–32,000 m² for a 100 m buffer. A second user
  cannot retrieve its output and is not charged for its tokens. Also checked
  stale selections, invalid input, busy worker, token/storage exhaustion,
  runtime recovery and deadline cleanup.
  The selected-feature test now uses the actual OpenAI engine implementation,
  mocking only provider transport. Additional tests cover both OpenAI/Claude
  chat contracts, argument validation before token reservation, and safe error
  IDs without provider payloads or secrets in diagnostic logs.
- `python tests/isolated_worker_regression.py`: real-container boundary test
  passed: UID 65534, no network, no Docker socket/account DB/API keys, read-only
  application filesystem and successful GIS output.
- Python compilation and `git diff --check` passed.

The standalone HTTP suites must run as separate processes because each creates
its own temporary workspace before importing the application. The analysis suite
requires the dedicated rootless socket and `GISCLAW_ISOLATED_ANALYSIS=1`;
the storage suite uses `GISCLAW_ISOLATED_ANALYSIS=0` and mocks worker replies.

## Fixes verified

- Fixed missing required `prompt` in both isolated analysis and text chat.
  Earlier permissive `generate(**kwargs)` test doubles masked this defect;
  the updated tests exercise the real engine signatures and implementations.
  Invalid calls are rejected before reserving any tokens. Existing historical
  reservations have not been changed or assumed to be unbilled.
- Unexpected analysis failures now distinguish provider, worker connection,
  missing-resource, storage-permission and internal failures, with a reference
  ID for safe server-side diagnostics instead of the generic quota warning.
- Default to text chat, which does not require a selected project; show the exact
  reason when GIS Run is disabled. Ignore unrelated legacy runs in isolated mode.
- Model answers (including off-topic replies) remain in the chat, not a modal.
- Preserve actionable analysis errors with appropriate 409/413/429/503/504 status.
- Refresh runtime readiness after temporary failure instead of caching forever.
- Serialize timeout cleanup so worker removal completes before the job slot frees.
- Set the actual PROJ data directory in the container image; final runs produced
  no previous PROJ initialization warning and spatial area checks passed.

## Not verified

- Full legacy pytest suite: pytest/httpx could not be downloaded from the package
  index (container and host attempts failed). The stdlib suites above did run.
- Visual browser interaction: the in-app browser was unavailable in this session.
- Real external model connectivity/output quality: no live provider call was made.

Passing these checks is not a guarantee of zero bugs or a public-deployment
security audit. See isolated-analysis.md for the remaining deployment limitations.

## Deployment verification

The tested candidate was deployed to `gisclaw_rootless_app` on port 8765.
The served JS SHA-256 matches the built `index-BL6-OLnF.js` asset. Regular-user
chat/analysis/isolation capabilities are enabled; five models are configured as
ready (configuration status only, not provider connectivity). Anonymous chat
requests return HTTP 401. The previous image is retained as
`gisclaw:before-run-button-fix` for rollback. Temporary test accounts and files
were outside the production workspace.

Follow-up model-contract fix: deployed image
`sha256:4e22e412a9bc3cd57721a604411a96c52b6c0c20ac42ff1497d4a42a839d33ae`.
The app returns HTTP 200, isolated runtime readiness is true, and checksums of
`isolated_analysis.py`, `chat_api.py` and `token_budget.py` match the tested source.
The pre-fix image is retained as `gisclaw:before-model-contract-fix`.
The follow-up run passed 7 analysis/chat tests, 1 storage regression, 21 urban/DBF
tests and 1 real worker boundary test. Provider transport was still mocked;
this does not verify external model availability.

## Historical token reservation repair

The missing-prompt fix prevented new invalid reservations but did not release
existing ones. One affected regular account had zero reported usage and three
pre-fix reservations totalling 10,000 (3,526 + 3,522 + 2,952).
Added an operator-only, scoped reconciliation method with transactional audit
records and idempotency. It rejects already-settled usage and wrong account IDs;
it is not exposed as an HTTP endpoint and does not expire uncertain reservations.
Quota errors now distinguish reported usage from reserved/unconfirmed usage.

`PYTHONPATH=. python3 tests/token_reconciliation_regression.py`: 6 tests passed,
covering the exact historical amounts, persistence, idempotent/concurrent repair,
tenant protection, unchanged settled usage, ambiguous provider failures,
exhaustion messages and missing-prompt rejection before reservation.

The follow-up candidate also passed the 7 analysis/chat and 1 storage tests.
Deployed image: `sha256:676f8ba906c2e7336fd9073f2fc572e293b403f2483047738c1e80405a6ac1fd`.
Before repair, a SQLite backup was verified with `PRAGMA integrity_check`:
`/workspace/.gisclaw/accounts-before-token-repair-20261107-153713.sqlite3`.
The three identified pre-fix reservations were manually reconciled with an audit
reason recording the user's no-usage report and the reproduced pre-provider bug;
external provider billing was not independently verified. After repair: limit
10,000, reported usage 0, reserved 0, remaining 10,000. Other accounts' request
records were compared before/after and were unchanged. No reservation was deleted.
The deployed app returns HTTP 200; rollback image:
`gisclaw:before-token-reconciliation`.

## Optional unmetered test mode (prepared, not deployed)

Added server setting `GISCLAW_TOKEN_BUDGET_ENABLED=0` to bypass account quota
checks and accounting without deleting history. UI shows test mode and provider
billing warning instead of numeric quota. Missing setting defaults to enabled.
The existing locally edited default `TOKEN_LIMIT=100000` was preserved.

Checks passed: 8 offline accounting/reconciliation tests, 8 HTTP analysis/chat
tests with actual rootless workers, 1 storage regression, both frontend test files,
and production frontend build. The new HTTP test uses an account with zero quota,
performs text chat and creates a real GIS buffer output in disabled mode, and
asserts token records are unchanged. Provider responses are scripted, not billed.

Candidate image:
`sha256:df9e3d75f31bbe8f3ff2fb8e21750c90801dec7152574e8c486599ceffc62e03`.
Deployment was rejected by automatic safety review because disabling accounting
for all users on the live service needs explicit confirmation of provider-cost
risk. No replacement or live bypass occurred. `.env` remains set to `1` pending
that confirmation; do not treat this candidate as already deployed.

## Input snapshot scope fix — 2026-11-20 (deployed)

The latest live configuration has account token accounting and text-only chat
disabled; GIS chat uses the isolated worker. Historical deployment notes above
describe earlier states, not the current configuration.

The `landuse` analysis returned HTTP 413 because the old snapshot copied both
37.44 MiB of source data and 52.68 MiB of historical outputs. Snapshots now include
source data plus only explicitly selected output layers and their shapefile
companions. Historical outputs remain on disk. The combined 50 MiB worker-input
limit, storage quotas, bounded reads and symlink/path checks are retained.

Checks passed: 6 snapshot regression tests, 8 HTTP analysis tests, 1 storage
regression and 1 real worker GIS/isolation test (16 total). The HTTP GIS test
creates a real selected-feature buffer with an unrelated 55 MiB historical
output present; the old output remains unchanged. Model responses are scripted;
no live provider call or browser visual test was performed.

Deployed image:
`sha256:156068c06cde0edd952fafc852174fc614d6cb4f6131151c8631b3a5ca44b0c5`.
Rollback tag: `shahrkav:before-input-scope-fix`.
Post-deployment HTTP status is 200 and isolated-worker readiness is true.
A read-only snapshot of the real `landuse` project contains 7 source files,
37.44 MiB, and no unselected historical outputs. Selecting a large output can
still exceed the input cap; the error now reports the measured size and limit.

## GIS conversation final-answer fix — 2026-11-20 (deployed)

Two local defects were found independently of the provider's intermittent
timeouts/502s: greetings entered the file-output guard loop, and normal `finish`
history entries omitted the observation that the isolated worker used as its
final answer. Added opt-in `respond(summary)` for answer-only GIS conversations;
normal `finish` retains output checks and now records its complete observation.
The worker returns the final answer without toolkit file-list boilerplate.
The separate text-chat endpoint and account token accounting remain disabled.

Checks passed: 4 agent response tests, 9 HTTP/real-worker analysis tests,
6 input snapshot tests, 1 storage test and 1 worker boundary/GIS test (21 total).
The HTTP suite checks exact final-answer text and a one-call greeting with no
outputs. All four frontend test files pass, including real ChatPanel server
rendering for a successful analysis, a greeting without files, 502 and 504.
This is not visual browser verification; no in-app browser was available.

A live `kimi-3` test with the corrected worker returned a Persian greeting in
9.08 seconds, exactly one model call, zero outputs. It sent only the greeting
and static program instructions: no real project files. A proposed real-project
diagnostic was rejected by safety review and was not run. Passing this greeting
does not establish availability of every provider/model or eliminate upstream
errors.

Deployed image:
`sha256:61c043fd7e091da0616439d439bd875a10b6ef88d290ab2a5ec4dd882506bf4a`.
Rollback: `shahrkav:before-gis-reply-fix`. After deployment: HTTP 200,
isolated runtime ready, deployed worker/agent checksums match tested source.
The disposable test container was removed; production files were not deleted.

## Analysis failure classification — 2026-11-20

The reported landuse request failed with HTTP 400 after approximately 19 seconds.
Its old ValueError handler logged no cause, so this historical failure cannot be
attributed reliably to time, memory, output size or malformed data. Docker exit
137 events alone are not OOM evidence: normal coordinator cleanup kills workers.

Replaced the combined size/time/validity message with fixed codes for worker EOF,
invalid JSON/messages, oversized model context, RPC limits, malformed output
files, temporary storage, memory allocation and output size. Every AnalysisError
now has a correlation ID. Unexpected ValueErrors log only exception type and
stack locations, never payloads or exception messages. Workers send allowlisted
error codes instead of raw traceback contents; existing resource limits remain.

26 backend checks passed: 3 protocol, 2 synthetic landuse worker, 9 HTTP analysis,
4 agent response, 6 snapshot, 1 storage and 1 isolation test. The landuse fixture
has four projected 100-by-100 metre polygons: both categories produce 2 hectares,
2 features and 50 percent in the verified CSV. Another real-worker test verifies
that output overflow becomes a specific HTTP-413-class error. All four frontend
test files passed. Provider responses in these checks are scripted.

A separate live Kimi attempt using only four synthetic polygons failed at the
first model call with ApiCallFailed after 12.51 seconds; no GIS tool was executed.
No real project data was used in diagnostics. The original user's analysis is
not yet verified successful; a repeat with the new correlation ID is required.

Candidate/deployed image:
`sha256:e27603be368f77ad4ece15ba60762c46e075187b1773c878284223bb51502165`.
Rollback: `shahrkav:before-analysis-error-details`.

## Temporary removal of model-message character quota — 2026-11-20

At the user's explicit request, removed the coordinator's 32,000-character
rejection for combined model system/user messages. Non-string messages still
fail with `analysis_context_invalid` (502), now with a type-specific explanation.
No account storage, worker resource, RPC frame, timeout or provider-side limit
was removed. Existing agent history compaction and per-response budgets remain.
Longer requests can increase provider cost and latency.

16 tests passed: 5 protocol tests, 9 HTTP/real-worker analysis tests and
2 synthetic landuse tests. Regression coverage verifies that 32,001 combined
characters and a much longer Persian prompt reach the model wrapper unchanged,
while null, list, object and numeric message fields are rejected. Provider calls
were mocked; no live large-prompt request was made.

Image: `sha256:86f77dc0083a912f5c92b6c680c706d292b4204bd3ad417a777d61fc7c810df7`.
Rollback: `shahrkav:before-no-context-cap`.

## Longer model-response wait for testing — 2026-11-20

Request `0cd3476d0e6d` failed with ModelTimeout while using `kimi-3` and the
effective SDK timeout was still 60 seconds. The removal of the character quota
did not change that timeout. Set `GISCLAW_LLM_TIMEOUT_SECONDS=180` in the local
deployment `.env`; no code/image change is required. SDK retries stay disabled,
and the complete isolated job retains its 300-second deadline.

Three targeted transport tests passed: initialization applies configured values,
invalid timeout settings are rejected, and the real OpenAI-compatible SDK uses
180 seconds with one attempt and a safely classified timeout under a mock HTTP
transport. No real provider request was made in this check; increasing the wait
does not establish that the failed real analysis will complete or fix an upstream
outage. Account token accounting remains disabled. To undo this setting, restore
the environment value to 60 and recreate the Compose service.
