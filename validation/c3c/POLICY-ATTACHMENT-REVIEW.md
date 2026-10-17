# C3C same-runner native sandbox validation candidate

Decision: **READY FOR ONE SEPARATELY AUTHORIZED CONTROLLED NATIVE ATTEMPT**.
This is preparation readiness, not a native security acceptance result. No commit,
push, Actions run, policy load, Chromium launch or infrastructure change was made
in this preparation session.

## Verified lineage and preserved inputs

- Review parent: `ef0dfc6e6d9a12aca3f8319c2ca2634bbead17b1`.
- Required main: `36c98ecd4537cc421e0ffe08321f62a10b0bed36`.
- Recovered 20-path candidate manifest SHA256:
  `198772ce66a13d69bf51ef000e1543fab6457b11f3501a7377f081443af20bf1`.
- Preserved ten-file policy proposal manifest SHA256:
  `889e6ebecddd34139a02f9c835bdd328881b6a8c30e2dbaaf91d1ab48b1eb33b`.
- Existing 48 engineering files, dependency/browser/image pins and logging-only
  engineering corrections remain byte-identical to the review parent.
- The original recovered candidate remains intact in its separate worktree.
- Capability run 39039640045 actually passed eight structural checks. Its observed
  Ubuntu 24.04.5/kernel 6.17.0-1022-azure/Python 3.12.3/Docker 28.0.4 environment
  supplied AppArmor userns mediation, ABI/parser 4+ compilation, raw policy hashes,
  cgroup v2 controllers, restricted user namespaces and potential load authority.
  Those observations do not prove an actual custom profile load or attachment.

## Exact incremental changes to the recovered candidate

1. `.github/workflows/c3c-security-validation.yml`: restore one native job; guard
   public repository, exact new push parent and attempt 1; depth eight; scoped
   profile preparation and two always-run cleanup steps in the same VM/job.
2. `validation/c3c/run.py`: refresh lineage, remote main and ancestry guards;
   persist job-specific resource ownership intentions; reject existing images,
   containers and volumes; scope the preserved external reaper to its fixture;
   validate explicit negative/namespace/browser/DOM evidence; restrict final
   cleanup to recorded identities; expose a cleanup-only entry point.
3. `validation/c3c/policy_attachment.py`: root-owned receipt, fixed add-only binary
   profile load, enforcing raw-hash verification, unprivileged read-only receipt
   verification, pre-existing-policy preservation and exact owned-profile removal.
4. `validation/c3c/namespace_diagnostics.py`: require all five outer capability
   sets to be empty, including permitted/inheritable/ambient sets.
5. `validation/c3c/sandbox_probe.py`: emit explicit synthetic DOM success evidence.
6. `validation/c3c/test_preflight.py`: update parent/depth and modeled publication
   guards; retain diagnostics/exit/timeout assertions with readiness mocked.
7. `validation/c3c/test_policy_attachment.py`: retain existing 25 checks and add
   21 focused lifecycle, collision, ownership, ordering and fail-closed checks.
8. `validation/c3c/candidate-manifest.json`: refresh exact parent, hashes and
   preparation evidence while preserving the same 20 publication paths.
9. `validation/c3c/POLICY-ATTACHMENT-REVIEW.md`: this review and execution contract.

The other eleven paths in the 20-path candidate are unchanged from the recovered
candidate. All ten policy-proposal files, including their historical proposal-only
comments and historical lineage, are deliberately unchanged. The current candidate
manifest is the publication lineage authority; the nested proposal is an immutable
historical input. No production supervisor, controller or broker code is changed.

## Single-VM sequence and independent controls

1. Verify all source/candidate hashes, proposal identity, public first-attempt push,
   exact parent/path manifest, main ancestry and current remote main. Only the C3C
   workflow runs on this review branch; the other workflow excludes it.
2. A narrowly invoked `sudo -n /usr/bin/python3 -I` helper performs the successful
   probe's structural checks again in the actual validation VM: system Python 3.12,
   amd64, reviewed local Docker/defaults, cgroup controllers, AppArmor/userns
   features and sysctls, parser/ABI/imports, readable hashes and administration
   metadata. Missing prerequisites stop before policy loading or containers.
3. Refuse ANY existing `c3c-chromium-userns-review` profile, even if identical.
   Snapshot every pre-existing profile's enforcing mode and raw binary hash in a
   root-owned exclusive `/run/c3c-sandbox-RUNID-1` directory (mode 0700).
4. Compile exact reviewed source with real host features/imports and skip-load,
   skip-cache, warnings-as-errors options. Save the exact binary privately.
   `apparmor_parser --add --binary` loads that binary; never use replace mode,
   global policy reload, sysctl changes or daemon configuration changes.
5. Persist successful ownership only after the add operation returns successfully.
   Require kernel `raw_sha256` to equal the saved load binary, mode `enforce`,
   host recompilation to match, and all pre-existing profiles to remain unchanged.
   An uncertain/timed-out load cannot authorize the browser or blind removal.
6. Only the synthetic sandbox-probe worker receives exact custom seccomp JSON and
   the separate AppArmor profile. UID/GID 10001, empty capabilities, NoNewPrivs,
   network none, private IPC/cgroup/PID modes, read-only root, 1536 MiB memory/swap,
   64 PIDs, 1 CPU, 256 MiB tmpfs, ulimits and bounded local logs are unchanged.
   Controller/broker/resource/IPC-denial fixtures retain their original boundaries.
7. Before start, require Docker inspect to expose exact effective seccomp JSON,
   profile/image/user/resources/mount identity. Recheck root-owned policy receipt
   immediately before start. In-container guards require the enforcing label,
   seccomp filtering, all empty outer capability sets and NoNewPrivs before any
   browser operation. This combines host identity with in-container enforcement
   evidence rather than trusting a profile name or Docker configuration alone.
8. Before Chromium, require denied setns, mount, outer chroot, unshare(0) and mount
   namespace operations. Then run the existing bounded userns/zygote prerequisite
   children. Stop immediately on any negative/prerequisite failure. No broad
   namespace allowance or new policy rule is introduced.
9. Require pinned Chromium 156.0.8078.4 secure startup, positive chrome://sandbox
   evidence including Seccomp-BPF, and JavaScript DOM rendering in the original
   secure context. Empty logs or exit 0 alone cannot pass these gates. Preserve
   sanitized stderr, launch exceptions and separate Docker/Chromium exit evidence.
10. Preserve native PID/memory/CPU/storage fixtures, expiry reaper, signed Unix API,
    and separate real broker IPC/private-destination/schema-denial integration.
    The broker IPC stage follows a successful browser gate. It is not a positive
    broker-backed HTTP/rendering or mTLS test; those remain NOT VERIFIED.
11. Cleanup checks exact known job nonces/names/labels and previously absent image
    references. It never prunes all managed resources, overwrites foreign tags or
    adopts name collisions. Always-run resource cleanup covers recorded creation
    intent even if the native process was terminated after create succeeded.
12. Policy cleanup refuses any attached container, requires the root-owned success
    receipt and exact loaded enforcing binary hash, and uses `--remove --binary`
    with the same private binary. It confirms profile absence and preservation of
    every pre-existing profile. It removes only its two known receipt files and
    exclusive directory; it never restores or rewrites host-wide defaults.

## Workflow limits and cleanup headroom

One standard `ubuntu-24.04` job; original 20-minute job ceiling retained. Checkout,
setup and offline checks each have a one-minute ceiling. Policy preparation is
60 seconds plus 5-second kill grace; native execution is reduced from 1050 to
780 seconds plus 30-second kill grace. Each cleanup is 60 seconds plus 5-second
kill grace. These command/action budgets total 1185 seconds, reserving cleanup
headroom within 1200 seconds. No assertion or container resource limit is relaxed
if time expires. Platform cancellation or VM loss can still interrupt cleanup;
cleanup must then remain NOT VERIFIED and the disposable VM lifecycle is the final
boundary. Do not claim graceful cleanup from infrastructure teardown alone.

All evidence is bounded Actions logs. No artifacts, cache/image uploads, paid
runners, retries/matrix, production secrets, PR, merge, deployment or provisioning.
The scoped administrative helper is host policy administration only; Chromium and
all workload containers continue to run non-root with zero outer capabilities.

## Offline results and remaining native gates

- Focused diagnostic/image regressions: **45/45 PASS**.
- Preserved exact-policy/compiler-output/negative BPF checks: **19/19 PASS**.
- Attachment/lifecycle/cleanup tests: **46/46 PASS**, including 21 new cases.
- Total focused checks: **110/110 PASS**; lifecycle operations mocked, no host
  kernel policy is loaded. An additional run simulates non-root effective-UID
  branching. An actual separate non-root process is NOT VERIFIED here: this Work
  runtime rejects runuser group changes (Operation not permitted).
- Existing workflow safety categories: **11/11 PASS**, with added lifecycle order,
  root-helper scope, fresh ancestry, cleanup and bounded-budget assertions.
- Future publication lineage, exact 20-path scope, cumulative baseline scope,
  eight-deep checkout ancestry, proposal/engineering preservation and hashes: PASS.
- Full engineering suite is not rerun unnecessarily during preparation. The locked
  full regression remains a mandatory native-job stage before integrated builds.

**NOT VERIFIED until the authorized fresh-VM job executes:** actual add-only kernel
load/removal, matching enforcing loaded identity, effective custom attachment,
negative syscall enforcement/denial attribution, Chromium startup/sandbox/DOM,
resource/IPC/API/cleanup results for THIS candidate. The previously passed native
results remain historical evidence and are not re-labeled as this candidate's PASS.

The AppArmor `userns,` rule is a coarse permission within this one named worker
profile; seccomp exact argument rules, kernel capability checks and outer Docker
controls remain independent. Do not weaken those controls if initialization fails.
The preserved final summary intentionally exits 2 for incomplete whole-system
acceptance even if all executed gates pass; inspect individual gate results rather
than treating a green job as the only acceptance signal. Standard runner images may drift; the repeated preflight must stop on incompatible
Docker/Python/platform/import/feature conditions. No infrastructure purchase is
currently justified by the successful structural probe.

## Next authorized execution, not performed here

After separate authorization, recheck remote main and review parent, publish exactly
these 20 paths as one review-branch child commit, and inspect ONE native attempt.
Do not publish a second workflow or bypass manifest/parent guards. Load, identity,
attachment, negative checks, browser/IPC and cleanup must stay in this same VM/job.
Report each actual native gate and every skipped gate independently.

## Primary interface references

- AppArmor parser add/remove/binary/skip-load semantics:
  https://manpages.ubuntu.com/manpages/noble/man8/apparmor_parser.8.html
- Docker separate named-profile attachment:
  https://docs.docker.com/engine/security/apparmor/
- Actual structural probe:
  https://github.com/SEOAuditSuite/SEO-Audit-Suite/actions/runs/39039640045

The parser interface supports the scoped mechanism; this is not proof that this
candidate has been loaded successfully. No new Chromium source investigation or
policy-rule development was repeated.


## Targeted hosted-environment fixture recovery

The unpublished commit `2856940031d170aff37b4c94adf080349ef2ce83` was not
attached to the review branch and triggered zero workflow runs. This candidate
supersedes it as another child of the unchanged remote review head.

The three errors shared environment leakage: direct-host attachment fixtures
inherited workflow-level C3C_POLICY_JOB, so a non-root caller entered privileged
receipt verification before profile preparation. AttachmentTests now clears only
that variable for its direct-host fixtures and installs a fail-fast guard against
any accidental privileged receipt query. Production code is unchanged. The existing
hosted receipt test explicitly covers non-root delegation, valid identity, changed
identity rejection and missing-receipt rejection with mocked receipts. No security
assertion is removed, and the focused test count remains 110.

Both normal and hosted-job effective-UID contexts are tested offline. Actual UID
switching is unavailable in this Work runtime (subprocess user change returns
EINVAL). The hosted context therefore emulates effective UID 1001; this is not
reported as an actual non-root OS process. In the single authorized native job,
the existing first test step runs all 110 checks under the actual runner account
with the real workflow environment, before any policy preparation. Any failure
skips preparation/native execution; always-run scoped cleanup remains in place.

Incremental changes from the unpublished commit are limited to this review,
`test_policy_attachment.py` and candidate manifest/checksum metadata. Workflow,
production receipt validation, runtime, policies, dependencies and limits remain
byte-identical to that candidate.
