# C3C post-launch timeout and AppArmor cleanup recovery

Decision: **BLOCKED pending matching Linux offline regressions**. The correction
is prepared, but Windows-only results cannot qualify another native attempt.
No commit, push, Actions run, pull request, merge, deployment or policy load was
performed in this session. Local HEAD remains the exact review parent.

## Evidence and root-cause boundaries

- Parent: `89ac410c49b036c3866be411c57079a4b90af9ab`.
- Required main: `36c98ecd4537cc421e0ffe08321f62a10b0bed36`.
- Failed run: [39041775988](https://github.com/SEOAuditSuite/SEO-Audit-Suite/actions/runs/39041775988),
  job 117422553714, attempt 1.
- At 14:44:04.4450713 UTC the collected log reports pinned Chromium STARTED.
  At 14:44:04.4783104 UTC it reports attach_timeout=true, running=true,
  oom_killed=false. These are collection timestamps; the previous probe did not
  emit individual post-launch timestamps.
- The previous sequence was launch -> version -> sandbox new_context -> new_page
  -> chrome://sandbox navigation -> body extraction -> sandbox assertion -> close
  -> secure_context setup -> new_page -> synthetic content -> DOM extraction ->
  context/browser/driver close. Only navigation had a 10s timeout. Other calls
  inherited SDK defaults or had no explicit timeout, while Docker attachment had
  a 40s total limit. Stderr was drained privately and printed only on context
  exit, so an outer timeout could lose the retained stderr.
- **Exact browser stall phase/cause is still UNKNOWN.** STARTED excludes failure
  to return from the successful Chromium launch; it does not prove subsequent
  page, renderer, sandbox, DOM or clean shutdown success. No policy relaxation
  or speculative rendering correction has been made.
- At 14:44:05.8626029 UTC cleanup reports parser exit 22 and
  `Invalid load option specified: 2`.
  [AppArmor 4.0.1 parser_main.c](https://gitlab.com/apparmor/apparmor/-/blob/v4.0.1/parser/parser_main.c#L960)
  routes binary input through process_binary, which accepts ADD/REPLACE and
  rejects REMOVE with EINVAL. In contrast,
  [parser_interface.c](https://gitlab.com/apparmor/apparmor/-/blob/v4.0.1/parser/parser_interface.c#L524)
  removes a parsed source profile by its fully qualified name. The loaded binary
  hash is an ownership guard, not the removal operand. This explains the observed
  error; the installed runner binary has not been locally executed here.

## Correction scope

1. `sandbox_probe.py`: flushed BEGIN/PASS/FAIL records for driver connection,
   launch, version, context/page creation, navigation, sandbox text/assertion,
   original secure_context setup, content, DOM and each close. Every phase has a
   5s ceiling, launch 10s and close operations 2s; all share an absolute 34s budget
   measured from probe entry. SDK-supported timeouts use the remaining budget.
   A watchdog handles APIs without timeout arguments, reports sanitized bounded
   retained stderr and container-local process status, then exits 124. It starts
   after the original single-threaded namespace checks. The host remains
   responsible for removing the capped container and verifying zero survivors.
   Process evidence reads only PID, Name, State, PPid, Threads, NoNewPrivs,
   Seccomp and wchan (maximum 64 rows), never cmdline or environment.
2. `policy_attachment.py`: retain the private load binary/hash; verify exclusive
   ownership, enforcing identity, original profile absence at preparation,
   unchanged pre-existing profiles and no attached containers. Write a minimal
   fixed-name source in the root-owned receipt directory; verify its sole parsed
   name without kernel loading; recheck enforcing identity immediately before
   removal. Use parser --remove with source, without --binary, --replace, global
   deletion or policy weakening. Record removal_pending before the operation.
   Verify kernel absence and pre-existing identities before reporting success.
   Failed parser/absence/preservation/file cleanup keeps a failed result; a later
   retry can verify absence after recorded partial removal without unloading a
   replacement or unrelated profile. Missing receipt removes nothing.
3. `test_preflight.py` and `test_policy_attachment.py`: phase/deadline, real
   synthetic stalled child, sanitized diagnostics, modeled browser sequencing,
   negative sandbox, close failure, source removal, identity mismatch, bad parsed
   names, private binary conflict, partial removal/file cleanup, replacement,
   unexplained absence and repeated-cleanup regressions.
4. `run.py`, workflow and candidate manifest: refresh the exact future parent to
   this review commit. The branch-only/public/first-attempt guards and source
   hash checks remain; the workflow is not triggered in this session.
5. This review replaces stale preparation claims with the observed failed-run
   evidence and current validation limits.

The exact eight-file scope is in candidate-manifest.json. All 48 engineering
files and all ten immutable proposal files must be byte-identical to the parent.
Dependency/image/browser pins, user 10001:10001, zero capabilities, NoNewPrivs,
network/IPC isolation, seccomp/AppArmor rules and resource limits are unchanged.
The 40s browser attachment, 780s execution and 20-minute job ceilings remain.
The existing aggregate action/command budgets including grace total 1185s,
leaving 15s of the 1200s job ceiling; this narrow margin is unchanged, not a claim
that every worst-case setup/runner overhead fits. No deadline was increased.

## Validation and later acceptance

See the accompanying recovery report, test logs and preservation.json for actual
local results. The current Windows Python 3.12.10 host lacks Linux getuid/geteuid,
O_NOFOLLOW, statvfs, SIGKILL, pipe-select semantics and libseccomp. The recovered
Linux dependency environment is also unavailable for the complete suite.
These constraints are not evidence of a Chromium/hosting incompatibility.
Do not reuse the earlier 110/110 or 425/425 result as proof of this new candidate.

Before another native attempt, run all focused and negative-policy suites in
the matching Linux/Python 3.12 environment, including the hosted C3C_POLICY_JOB
fixture path, and require a clean full relevant regression result and safety
check. Then separately authorize publication and exactly one fresh VM/job attempt.
This session does not grant that authorization. Native acceptance still requires
all existing negative controls, exact attachment, pinned browser/sandbox/DOM,
resource enforcement, IPC and cleanup gates. A native result must identify a
failed phase and retain fail-closed cleanup status rather than infer success.

Positive broker rendering, mTLS, external network containment, crash recovery
and cancellation remain **NOT VERIFIED**. The new source unload/absence path and
post-launch diagnostics have no genuine kernel/browser acceptance evidence yet.

## Page-crash resource attribution candidate — 2026-10-18

Parent: `ec91c6af312f910050f236907a8c2632ddc47079`.
Required main: `36c98ecd4537cc421e0ffe08321f62a10b0bed36`.
Evidence: https://github.com/SEOAuditSuite/SEO-Audit-Suite/actions/runs/39050128092
(job 117446837887). Actual job logs were retrieved and inspected in this session.

### Observed findings and limits

Pinned Chromium 156.0.8078.4 launches as UID 10001 and Playwright connects;
browser context creation succeeds. Sandbox-page creation fails with
`BrowserContext.new_page: Target crashed`. Browser stderr repeatedly records
`pthread_create: Resource temporarily unavailable (11)` and network-service
restart failures. This establishes failed thread allocation, not the particular
limiting resource. No policy-denial cause is established by these messages.

The worker has pids.max=64, 1536 MiB memory, one CPU, no swap beyond the memory
limit, nofile=256, private IPC, 64 MiB /dev/shm and 256 MiB /tmp. Early pids.current=1
and pids.events max=0 precede browser startup. The post-crash process snapshot
contains 59 observed threads across eight processes. This is a racy, post-failure
sample and cannot exclude an earlier 64-task peak. Docker OOMKilled=false does
not exclude memory allocation pressure. Early memory/shm readings cannot prove
availability at failure. The SDK launch includes --disable-dev-shm-usage, making
/tmp and memory evidence relevant as well as /dev/shm; no launch flags change.

Chromium is a multi-process, multi-thread workload: the Python probe/watchdog,
Playwright driver, browser, zygotes, utility/network/GPU services and renderer
all share the task budget. A task cap counts threads, not just process leaders.
Compatibility of the exact pinned workload with 64 tasks remains NOT VERIFIED;
there is no defensible numerical replacement cap from this evidence.

### Minimal read-only instrumentation

Use existing phase callbacks/watchdog only; add no worker threads or processes.
Capture before and after browser launch and both page-creation phases, and on
any phase failure or hard timeout, before browser/context teardown:

- pids.current/max/peak and pids.events/events.local;
- memory.current/max/peak and memory.events/events.local;
- numeric namespace process/thread totals with completeness and race caveats;
- launcher RLIMIT_NPROC, STACK, AS, NOFILE and CORE (children may alter limits);
- host threads-max, pid_max, aggregate scheduler tasks and available/committed memory;
- available bytes and inodes for /tmp and /dev/shm.

Reads are size bounded; numeric files reject malformed/oversized content;
missing evidence stays NOT VERIFIED. No commands, environments, credentials,
host process names or arbitrary file contents are added to logs. Existing
sanitization, 8192-character driver stderr and 32768-byte Docker evidence bounds
remain unchanged. A bounds breach remains a failing evidence gate.

Event deltas are emitted, never converted to acceptance PASS. A positive PID
event delta supports cgroup PID enforcement during the sampled interval;
64-task leaf attribution still requires the corresponding limit/peak and
hierarchy interpretation. Zero delta, current below max, a counter reset or
missing counters cannot prove compatibility. Memory events and space samples
must be assessed independently. Private namespaces hide ancestor cgroup limits
and host-wide UID task totals; both remain explicitly NOT VERIFIED. If leaf
counters do not resolve attribution, a separately reviewed host-side observation
of the owned worker's ancestor cgroups and UID task totals is the next diagnostic,
not a speculative limit increase. No host security changes are proposed.

Kernel references:
https://docs.kernel.org/admin-guide/cgroup-v2.html#pid
https://man7.org/linux/man-pages/man3/pthread_create.3.html

### Preservation and execution boundary

All 48 engineering files and ten policy-proposal paths must be byte-identical to
parent. No policy, image, dependency, UID, capability, namespace, sandbox, resource,
network or cleanup change. The six-path scope is the probe, tests, workflow,
runner lineage/safety constants, this review and candidate manifest. Checkout
fetch-depth=9 retains the main baseline for a proposed child eight edges above
main; the explicit ancestry, remote-main and exact-parent assertions remain.

Prior native policy load/attachment/source unload/absence, resource controls,
signed API and owned-resource cleanup results remain historical PASS evidence;
this candidate is not natively executed. Chromium sandbox-page verification and
synthetic DOM remain FAIL/incomplete in the cited run. Positive broker rendering,
mTLS, network containment and crash/cancellation acceptance remain NOT VERIFIED.
READY means ready only for one separately authorized attribution run, not native
security acceptance. No commit, push or Actions run is performed in this session.

### Offline validation results for this candidate

- 146/146 focused tests PASS on Linux/Python 3.12.14: 68 preflight/diagnostic,
  19 seccomp and 59 attachment/cleanup tests. Twelve new attribution tests pass.
- The same 146/146 PASS with C3C_POLICY_JOB and RUNNER_TEMP set. An initial
  incomplete environment omitted RUNNER_TEMP and caused two existing cleanup
  test errors; supplying the hosted fixture variable resolved both. This is
  environment simulation, not proof of native UID 10001 execution.
- 11/11 workflow safety checks PASS, including 128 source checksums and the
  two pre-existing explicitly documented logging-only corrections.
- Parent candidate hashes, 48/48 engineering and 10/10 policy preservation,
  exact six-path scope, proposal identity and git diff whitespace checks PASS.
- pip check PASS. Full application regression is not rerun for this diagnostic
  change; the cited prior native run's 425-test result is historical evidence.
- New resource evidence is NOT VERIFIED on a native browser workload. Prior raw
  browser evidence spans approximately 12.8k log characters; six new bounded
  numeric snapshots are expected to fit the unchanged 32768-byte capture, but
  actual native size is NOT VERIFIED and overflow fails closed.

Decision: READY for one separately authorized diagnostic attempt only. Do not
change the 64-task cap unless new native counter evidence justifies a reviewed
compatibility correction. No native execution or publication occurred here.

## Evidence-based PID budget compatibility review — 2026-10-18

This section supersedes earlier unknown attribution and 64-task validation-readiness
statements. Parent is a1a73548532b1aa8b001123dee0b0850c880700d; required main remains
36c98ecd4537cc421e0ffe08321f62a10b0bed36. No publication or native run is authorized here.

### Evidence and scope

Native run https://github.com/SEOAuditSuite/SEO-Audit-Suite/actions/runs/39110654959
confirmed 64/64 current and peak tasks, pids.events and pids.events.local max 0 -> 7,
thread-creation EAGAIN and renderer fork failure. Before page creation, the worker
had 57 tasks. A censored peak of 64 is a lower bound on demand, not a successful
working-set measurement. Seven denied attempts are not seven unique missing tasks:
retries and utility-service restarts prevent that inference. No upstream source
establishes a universal task count for Chromium 156.0.8078.4 in this workload.

| Boundary | Existing | Proposed in this candidate |
|---|---:|---:|
| Production Limits().pids default | 64 | 64, unchanged and browser compatibility BLOCKED |
| Production accepted configuration range | 16..128 | 16..128, unchanged |
| Synthetic browser worker | 64 | 128, provisional native compatibility ceiling |
| Exact worker attachment/readback requirement | 64 | 128 for synthetic browser only |
| Separate broker/worker denial-only IPC fixture | 16 / 64 | 16 / 64, unchanged |
| Existing PID/memory/CPU/storage resource fixtures | 8 tasks | 8 tasks, unchanged |
| New isolated PID-budget enforcement fixture | none | 128 tasks; sequential, <=15 seconds attached |
| Production admission/supervisor | one operation per shared private state | unchanged |

### Recommended budget and uncertainty

Recommend 128 tasks ONLY for the next synthetic native compatibility experiment.
This is the existing reviewed production policy's maximum configurable value,
not an expansion beyond its accepted range or a new production default. It gives
64 additional slots over the failed ceiling and 71 slots above observed pre-page
usage (57). These are allocated slots, NOT measured spare headroom. Selecting the
already bounded upper end avoids guessing 72/80/96 from retried denials and avoids
expanding the existing security range to 256/512. It does not prove that 128 is
sufficient, minimal, or safe for representative ten-page audits. This provisional
choice remains an engineering assumption until the mandatory native gates pass.

A fresh browser-only container must report the lifetime peak and unused slots,
with pids.max exactly 128 and pids.events max still zero after DOM extraction and
browser/driver close. Missing counters, PID denial or missing sandbox/DOM evidence
fail closed. No automatic increase, retry or fallback budget exists. A successful
single synthetic page establishes only that run's compatibility. Production
calibration requires representative repeated workloads, page-count variation,
measured peak variation, explicit reserve and aggregate host capacity review.

### Independent negative proof

Before image integration/browser launch, run the original four resource fixtures
and a separate 128-task negative fixture. The latter uses the immutable resource
fixture image, UID/GID 10001, no network, private IPC, read-only root, all caps
removed, NoNewPrivs, unchanged memory/CPU/tmpfs/nofile/core/logging bounds and
Docker's enforced defaults. It neither receives the custom browser profile nor
changes host policy. Read back the exact bounded Docker controls before start.

The payload forks at most 128 times and retains only its own child PIDs. PASS
requires EAGAIN, pids.current=128, pids.max=128, positive pids.events.max delta,
all owned children reaped, and current returning to one task. A generic Python,
permission or memory error cannot count as PID enforcement. Parent-side attach
has a 15-second timeout and finally removes only its nonce-labelled container,
then checks no owned survivor. Existing final cleanup remains the backstop.
This stress fixture never runs concurrently with Chromium; its pids.peak and
expected denial events cannot contaminate the fresh browser container's counters.
Actual 128-task kernel enforcement is NOT VERIFIED until native execution.

### Denial-of-service trade-offs and independent limits

The browser ceiling doubles the possible simultaneous kernel task objects from
64 to 128 for this one synthetic worker. CPU throttling does not itself bound
kernel-task memory or churn, and a PID cap does not bound task-creation rate.
Keep 1536 MiB RAM/no extra swap, 1 CPU, 256 MiB /tmp, 64 MiB private /dev/shm,
nofile=256, core=0, network none and the 34-second probe / 40-second Docker
budgets. The negative fixture is sequential and independently timed; the workflow
retains its 20-minute job bound and no upload/cache steps. Runtime, supervisor and
controller remain outside these cgroups; aggregate host budgets are NOT VERIFIED.

Existing supervisor active.lock applies only to callers sharing the same state
directory, not independently configured services across a host. Workflow
concurrency serializes this repository's validation group, not unrelated jobs.
Current production worker+broker ceilings remain 64+16=80. If a later reviewed
production configuration selected 128, that sibling sum would be 144; this
candidate neither selects that production configuration nor certifies capacity.
A single 128-task test is not authorization for more concurrent workers or a
multi-tenant deployment. Security policies, pins, sandbox and cleanup are unchanged.

### Exact scope and acceptance

Eight changed paths: the workflow, run.py, policy_attachment.py, sandbox_probe.py,
test_preflight.py, test_policy_attachment.py, this review, candidate-manifest.json.
All 48 engineering files and ten policy-proposal files remain byte-identical to
parent, including production defaults, dependency locks and source/proposal hashes.
Only the synthetic worker budget and its exact attachment/readback checks change.
The final browser snapshot and separate negative gate add acceptance evidence.
Checkout depth 10 retains main for the proposed child nine edges above baseline;
remote-main, exact-parent, single-attempt and push-only checks remain mandatory.

References: https://docs.kernel.org/admin-guide/cgroup-v2.html#pid and
https://playwright.dev/python/docs/docker. These document task accounting and
non-root sandbox requirements, not a guaranteed 128-task Chromium budget.

Broker-backed rendering, mTLS, network containment, active crash/cancellation,
production calibration and native 128-task compatibility remain NOT VERIFIED.
Decision is READY only for a separately authorized bounded native experiment,
conditional on all offline checks below passing; production release remains BLOCKED.

### Offline results and decision

- Linux/Python 3.12.14 focused: 162/162 PASS (68 preflight/diagnostics +
  19 seccomp + 75 attachment/cleanup/budget tests).
- Hosted-variable simulation (C3C_POLICY_JOB and RUNNER_TEMP): 162/162 PASS.
- Hosted-variable plus mocked effective UID 1001 branch simulation: 162/162 PASS.
  This is explicitly NOT actual UID switching or native kernel enforcement.
- New budget regressions: 16/16 PASS, including missing final evidence,
  missing sandbox/DOM, wrong/unlimited readback, false denial attribution,
  privilege/profile mutation and uncertain child cleanup rejection.
- Workflow safety: 11/11 PASS; 128 source checksums verified. No paid runner,
  artifacts, cache/image upload, retry or secondary workflow is introduced.
- 48/48 engineering and 10/10 proposal files byte-identical to parent;
  exact eight-path scope, proposal identity and whitespace checks PASS.
- Full application regression not repeated: no application/audit/export logic
  changes. Prior run's 425/425 PASS is historical, not this candidate's result.
- Native 128-task enforcement, browser compatibility, measured peak/headroom,
  sandbox-page and DOM acceptance, broker/network/mTLS, crash/cancellation and
  cleanup of this new fixture: NOT VERIFIED; none executed in this session.

READY for ONE separately authorized standard free-runner experiment with the
mandatory negative gate and unchanged acceptance gates. BLOCKED for production
budget/default changes or release. This candidate is uncommitted and unpublished.

## Targeted 128-task fixture recovery — 2026-10-18

Parent: 8cada86965c400276ceadbd8f9c28e4f5ffcbe93. Main must remain
36c98ecd4537cc421e0ffe08321f62a10b0bed36. Offline correction only: no commit,
push, workflow execution, policy loading or infrastructure changes in this session.

### What the failed run actually establishes

https://github.com/SEOAuditSuite/SEO-Audit-Suite/actions/runs/39112368807,
job 117631018542, records native_validation_128_task_enforcement FAIL with
AssertionError and an empty detail. The logs have a created container ID and owned
removal, but omit its inspect fields and the specific assertion. Chromium was
skipped. The exact historical failed assertion remains NOT VERIFIED; neither
AppArmor disablement nor 128-task incompatibility is established by this failure.

Docker 28.0.4 source distinguishes explicit AppArmor configuration from OCI
selection: daemon_unix.go assigns AppArmorProfile from an explicit apparmor
security option; oci_linux.go WithApparmor selects docker-default when the field
is empty and the container is unprivileged. The previous fixture omitted explicit
selection yet asserted the creation metadata already named docker-default.
That is an established source-level fixture assumption defect and a likely
explanation, not recovered native field evidence. The old mock supplied the
expected profile string unconditionally, so it did not model the empty creation
metadata case. New tests retain strict rejection of empty metadata after explicit
selection; no missing observation is relabelled PASS.

Primary source:
https://github.com/moby/moby/blob/v28.0.4/daemon/daemon_unix.go
https://github.com/moby/moby/blob/v28.0.4/daemon/oci_linux.go

### Exact correction and enforcement sequence

Only the separate synthetic negative fixture requests an explicit existing
`--security-opt apparmor=docker-default`. No custom browser policy is attached
to it, and browser options/policy attachment remain unchanged. Docker's global
default profile is neither replaced nor edited.

1. Obtain the existing read-only host/receipt preflight. Require the loaded,
   enforcing docker-default binary hash and unchanged job-owned named profile.
   A non-root hosted caller uses the existing privileged read-only receipt helper;
   no new privileged operation is introduced.
2. Create with the explicit profile option. Read back exact 128-task, UID 10001,
   zero added capabilities, cap-drop ALL, NoNewPrivs, memory/swap/CPU, private
   namespaces, network none, read-only root, tmpfs, ulimits, immutable image and
   explicit default AppArmor selection. Every mismatch names its field and
   bounded, sanitized expected/observed values. Duplicate security options fail.
3. Recheck the same host profile identities before container start. The payload
   verifies UID/GID, kernel `/proc/self/attr/current` exactly
   `docker-default (enforce)`, NoNewPrivs=1, seccomp=2, all five capability masks
   zero and pids.max=128 BEFORE any fork or saturation. It emits a bounded
   pre-saturation record. A Docker profile name alone is not enforcement proof.
4. Retain bounded 128-attempt saturation. Require EAGAIN, current=128, positive
   pids.events.max delta, owned-child kill/reaping and final current=1. All
   equality failures identify the expected and observed field. No generic
   permission/memory failure can count as PID enforcement.
5. Capture Docker attach exit/timeout and sanitized stdout/stderr using temporary
   files (retain at most 4096/2048 bytes respectively). Truncation fails closed.
   A nonzero payload exit prints its field-specific stderr before the gate fails.
   Parse exactly two records and verify their effective label and PID evidence.
6. Recheck host profile identity after execution; reject drift before acceptance.
   Always remove the exact nonce-owned fixture and check no owned survivor.
   Existing final resource and source-based profile cleanup remain untouched.

The identity chain is the host enforcing binary hash, explicit container profile
selection, in-kernel label before fork and matching host identity after execution.
It does not depend on container access to host securityfs. Host administrators and
kernel compromise are outside this shared-kernel observation model.

### Preserved scope and remaining uncertainty

All 48 engineering files and ten policy-proposal files, image/dependency pins,
AppArmor/seccomp sources, production PID default 64, broker 16, original resource
fixture 8, synthetic browser ceiling 128, sandbox, resource and cleanup controls
remain byte-identical to parent. Existing positive page/sandbox/DOM acceptance,
zero browser PID-denial requirement and fail-closed negative-before-positive
ordering are unchanged. No new native retry or automatic budget increase exists.

Exactly six changed paths: run.py, test_policy_attachment.py, test_preflight.py,
the existing workflow, this review and candidate-manifest.json. The workflow only
updates exact parent and checkout depth 11; the proposed child is ten ancestry
edges above required main, so baseline ancestry remains verifiable. The previous
prepared correction is preserved in parent; this patch does not recreate it.

Actual 128-task enforcement/reaping, effective profile attachment in the corrected
fixture, Chromium compatibility/peak/sandbox-page/DOM and cleanup of this revised
fixture remain NOT VERIFIED until one separately authorized native attempt.
Broker-backed rendering, mTLS, network containment and active crash/cancellation
acceptance also remain NOT VERIFIED. No production readiness claim is made.

### Recovery validation results

- Linux/Python 3.12.14: 178/178 focused PASS (68 diagnostics/preflight,
  19 seccomp, 91 attachment/cleanup/budget tests).
- Hosted C3C_POLICY_JOB + RUNNER_TEMP simulation: 178/178 PASS.
- Same hosted variables with mocked effective UID 1001: 178/178 PASS.
  This does not establish actual native UID switching or profile enforcement.
- Sixteen new targeted regressions PASS: explicit/missing selection, empty/wrong
  profile, effective complain label before fork, invalid/changed host identity,
  PID mismatch, privilege mutation, bounded/redacted diagnostics, timeout,
  nonzero exit and owned cleanup. Prior negative-security tests remain passing.
- Workflow safety: 11/11 PASS; 128 source hashes with the pre-existing two
  logging-only corrections verified. Exact six-path scope and whitespace PASS.
- 48/48 engineering and 10/10 policy-proposal files are byte-identical to parent.
- No full application regression rerun: application/export logic is unchanged.
- No Docker/PID saturation, Chromium, profile load/unload, commit, push or Actions
  run is performed. Revised fixture's native identity/enforcement/cleanup and
  browser compatibility remain NOT VERIFIED.

Decision: READY for one separately authorized controlled native attempt, with
all negative and positive gates mandatory. Production acceptance remains BLOCKED.
