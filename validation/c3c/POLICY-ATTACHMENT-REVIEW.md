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
