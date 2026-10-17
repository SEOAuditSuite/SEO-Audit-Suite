# Independent C3C Infrastructure Acceptance — All Native Gates Pending

Run on a disposable authorized Linux test host with no public exposure. Record baseline, source hashes, image IDs, kernel/runtime versions, effective firewall, cgroup controllers and policy. Do not execute stress fixtures on the developer host or the user's pressured Windows machine.

## 1. Independent network tests

- Run `python -m deployment.c3c.native_probe --inside-isolated-job` INSIDE a network-none test container, separately from Playwright/C1. Add the actual host gateway and host public addresses to the target list. A failed connection alone is NOT VERIFIED: pair it with reachable controlled canary services and packet/firewall evidence showing that prohibited traffic was dropped or had no external route. Never treat a nonexistent target as proof of filtering.
- Verify IPv4 loopback, IPv6 loopback, RFC1918, CGNAT, link-local, ULA, IPv4-mapped IPv6, metadata and provider-specific services. Verify the broker namespace separately: controlled public HTTP(S) allowed, private/host/metadata denied even when C1 validation is bypassed by a test-only raw socket probe.
- Test UDP/QUIC, direct DNS and TCP web traffic from the browser namespace, unsolicited incoming traffic, alternate interfaces/routes, host gateway aliases and redirects/DNS rebinding with controlled DNS/canary servers. Inspect packet captures independently. No sensitive service may share browser loopback.
- Confirm the broker's allowed resolver works; block all other DNS. Verify socket IPC cannot accept CONNECT/POST/arbitrary schemes or tunnel private requests. Check missing/expired broker produces unknown/incomplete evidence, not synthetic SEO errors.

## 2. Actual resource enforcement

Use the reviewed worker image with overridden entrypoint `python` and fixed module `deployment.c3c.native_limits`. Each fixture gets its own container, no network, non-root, all capabilities dropped, no-new-privileges, read-only root, memory/swap both 64 MiB, PID limit 8, CPU 0.20 and an 8-MiB /tmp tmpfs. Use **an external 15-second deadline and owned-container cleanup**. Run one fixture at a time, never concurrent with Chrome.

Command inside that capped container: `python -m deployment.c3c.native_limits --inside-capped-test-job --mode MODE`, where MODE is processes, memory, cpu or storage. Do not remove the fixture's native cgroup preflight.

After infrastructure approval, the serial native runner supplies those caps, a 15-second deadline, per-fixture logs/inspect evidence and cleanup checks:

`python -m deployment.c3c.native_runner --execute --worker-image sha256:YOUR_REVIEWED_LOCAL_IMAGE_ID --output NEW_PRIVATE_EVIDENCE_DIRECTORY`

Do not substitute a tag for the image ID. The runner stops on failed/inconclusive evidence and its overall status remains NOT VERIFIED until independent network, authentication, lifecycle and Chromium gates are completed. It deliberately does not build images, change firewall rules or claim full acceptance.

- Process: real creation is refused; verify `pids.events:max` increases and no remaining descendants. A Python exception alone is insufficient evidence.
- Memory: capture `memory.events:oom/oom_kill`, peak memory, container OOMKilled/exit state and unchanged unrelated sentinel. OOM termination is expected evidence; do not mark a missing result JSON as PASS.
- CPU: record actual CPU/wall time and `cpu.stat:nr_throttled/throttled_usec` changes under known demand. Validate against quota with documented scheduling tolerance; an idle process proves nothing.
- Storage: real write reaches ENOSPC on the small tmpfs; confirm bounded filesystem size and cleanup. Separately test host state/artifact/log quotas and TTL deletion.
- Run a representative complete audit including reports under calibrated whole-operation caps; measure both worker and broker plus supervisor/host headroom. Verify concurrent submission rejected while active. Do not claim per-worker caps cover the controller or host runtime.

## 3. Lifecycle and independent watchdog

Test infinite JavaScript, hung HTTP, cancelled request, browser crash, supervisor SIGKILL, stale/orphaned jobs, reaper restart, daemon interruption and host restart. Record elapsed deadlines, cleanup commands, surviving cgroups/processes/volumes, external sentinel survival and partial result labels. Native acceptance requires zero owned survivors, bounded expiry reconciliation and no unrelated process termination. Runtime failure must stop new admission and report NOT VERIFIED. Do not silently accept cleanup uncertainty.

## 4. Filesystem and secret boundaries

Test UID, effective capabilities, seccomp, Chromium sandbox, rootfs writes denied, no host/runtime socket mounts, cross-job storage denied and socket directory read-only in worker. Place canary secrets only in the supervisor/controller and verify absent from worker environment, filesystem, browser, exports, error logs and process command lines. Test artifact quota, expiry and authorized download. Active HTML reports must download as attachments or be hosted on an isolated origin with restrictive policy.

## 5. Ingress and compatibility

Pending private-controller implementation: authenticate HTTP and WebSocket paths, reject unsigned/tampered/replayed/expired jobs, prevent cross-owner access/cancellation/download, preserve XSRF/CORS, enforce upload/rate/connection/queue limits and test certificate renewal. Test malformed/slow requests and unauthenticated application-port bypass.

Real Chromium must render controlled JS links/content and public CDN fixtures through the socket bridge while private fetches remain blocked. Compare baseline scores and all nine export bytes on fixed evidence; run existing Phase 1-3/C1-C3B regressions only when integrating into release. Verify Phase 3 remains same-origin. Review representative desktop/mobile report/screenshots after actual container integration. No existing Windows screenshot is evidence of this new Linux boundary.

## Acceptance record

For each gate store PASS, FAIL or NOT VERIFIED, executed command, timestamps, raw measurements, policy/image identity and cleanup evidence. No unattended/public deployment until every essential gate passes independently, C3B native evidence is reviewed, remaining controller integration is implemented, and explicit publication/deployment approval is granted.
