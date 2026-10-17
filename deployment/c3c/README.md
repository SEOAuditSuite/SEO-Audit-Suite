# C3C Containment Harness — Engineering Preview

**Public deployment: HOLD. No infrastructure acceptance is claimed.**

Baseline: `36c98ecd4537cc421e0ffe08321f62a10b0bed36`, plus the unchanged ten-file C3B R2 patch. The four supplied older V6.1 documents were read as background, not used as source baseline. Existing app source, scoring, local launcher, worker environment policy, nine default exports and C1/C2 restrictions are unchanged. This adds an optional deployment harness; it does not replace the local application.

## Implemented code versus actual acceptance

| Control | Implemented artifact | Acceptance status |
|---|---|---|
| Non-root, read-only jobs | Dockerfiles, fixed create flags and control readback | NOT VERIFIED: no Docker runtime |
| Whole-audit execution | Fixed job entrypoint invokes existing client delivery, including report generation | NOT VERIFIED in image; browser/sandbox/overlay integration pending |
| HTTP broker | Serial private Unix socket, C1 connection-bound GET, no redirect tunnel; bounded bytes/requests/time | Protocol unit tests executed; real IPC blocked by environment |
| Browser direct egress | Worker uses network none; broker in separate network; IPC volume read-only in worker | NOT VERIFIED: no namespaces/runtime/firewall privileges |
| CPU/memory/PID | Worker and broker hard-limit flags; no swap; readback refuses mismatches | NOT VERIFIED natively |
| Storage | Bounded tmpfs, 1-MiB socket volume, rotated runtime logs, per-file supervisor output limit | NOT VERIFIED natively; host state/artifact quotas required |
| Concurrency/admission | One trusted invocation at a time with nonblocking lock; zero waiting queue; signed expiring owner-bound job; one-use nonce | Deterministic tests executed; not a complete public controller |
| Deadline/cleanup | External supervisor removes both owned containers and IPC volume; ownership-filtered expiry reaper | Control-flow tests executed; native crash/deadline evidence pending |
| HTTPS/authentication | mTLS gateway example fails closed with 503; signed admission helper | Template only; identity mapping, private controller API and report authorization integration pending |
| Secrets | No job credentials or host mounts; signing key stays outside job; Unix socket permits only anonymous GET | Source/config tests executed; native filesystem/process inspection pending |

## Resource scope and calibration

Starting test configuration: worker 1536 MiB, broker 256 MiB, worker 64 PIDs plus broker 16 PIDs, worker 1 CPU plus broker 0.25 CPU, worker temporary storage 256 MiB plus broker 16 MiB and socket tmpfs 1 MiB. These are separate sibling caps, whose sum bounds the operation workloads; they are not a calibrated production service promise. Container memory semantics differ from Windows committed-memory limits. Page cache/tmpfs and Chromium sandbox requirements must be measured. Do not copy these numbers into production without profiling.

The supervisor and container runtime remain outside job cgroups. Enforce an independent supervisor service budget and a quota-limited state/artifact filesystem. Runtime logs are at most one nominal 10-MiB rotation file per container (allow implementation overhead). Output files are individually capped at 8 MiB using RLIMIT_FSIZE. Retention, disk quotas and log redaction are still infrastructure acceptance requirements. Do not accept arbitrary artifact filenames, HTML served inline from the application origin, secrets in request metadata or unbounded CSV uploads. The initial job schema only accepts URL and 1-10 pages; CSV upload, optional Phase 2/3 feature selection and interactive Streamlit remote use are not exposed by this harness. Existing local functionality remains intact.

Cleanup uncertainty creates an `ADMISSION-BLOCKED` marker. Subsequent jobs are rejected until an independent operator verifies cleanup; never delete that marker just to resume acceptance. Nonce replay prevention is separate from cleanup quarantine. Containers share the host kernel: use a dedicated VM with no unrelated client data, and assess a stronger sandbox/microVM boundary for hostile multi-tenant operation. This harness is not proof against browser/kernel escape.

## Network architecture and trust boundary

The worker container has no external route. Browser HTTP is fulfilled by the existing C2A/C1 policy through an image-only SafeSession overlay that contacts `/run/seo-broker/broker.sock`. Every spawned worker imports that same image module; no credential-bearing environment hook is added. Existing Phase 3 same-origin checks remain unchanged. Missing broker fails closed. Original `safe_http.py` is copied to `c1_transport.py` only while building the worker image. The broker image uses the original C1 implementation.

Network none retains loopback: do not place controller, credentials, metadata proxies or other sensitive services in that namespace. A compromised browser may contact its own worker-local services; this is not protection against browser/kernel compromise. IPC is a narrow broker capability, not arbitrary tunneling. Broker has no business/API credentials. Test that Chromium's sandbox launches with non-root, no-new-privileges and the host seccomp policy; never fix launch failure by adding `--no-sandbox`, privileged mode, host networking or unrestricted native network fallback.

Create a dedicated broker bridge with interface `seo-brk0` only in an approved Linux test environment. Review the nftables template for ALL host public addresses, host gateways, provider-specific virtual services, IPv4/IPv6/NAT behavior and Docker firewall backend. The initial template denies all forwarded IPv6; do not enable IPv6 without equivalent deny rules and testing. Only the trusted resolver and web ports are permitted. Its placeholder resolver deliberately fails until configured. No rules were applied here. Label the network `seo.c3c.egress=independently-tested` only after acceptance; the label is an operational admission guard, **not security evidence**.

## Build and test, without public exposure

1. Use a disposable Linux VM with Docker Engine, cgroup v2 controllers, suitable non-root Chromium sandbox support and host firewall control. Keep all public ports closed. Reserve host memory and disk independently of job limits.
2. Make a sanitized build directory from the verified source manifest. Exclude repository history, virtual environments, private files and generated evidence. Copy `.dockerignore.c3c` to `.dockerignore` there. Inspect the context before building. Never build from a personal project directory containing secrets.
3. Select a reviewed Playwright Python base **pinned by digest** and matching Python/Playwright browser versions. Review dependency resolution and record installed versions/SBOM; minimum-bound requirements are not a reproducible lock. Build `Dockerfile.worker` and `Dockerfile.broker` with `--build-arg BASE_IMAGE=...@sha256:...`. Build-time network is a separate trusted provisioning step; no build ran here.
4. Obtain local immutable `sha256:...` image IDs. Configure/test broker firewall, resolver, socket-volume ownership and cgroup controls. Collect independent results before labeling the network.
5. Create a mode-0700 supervisor state directory on a quota-limited filesystem and a separate mode-0600 signing key (at least 32 random bytes). A trusted authenticated controller signs `{owner,nonce,expires,url,pages}` using the policy's canonical JSON. Nonce is 32 hex characters; expiry at most 300 seconds. Never sign user-supplied owner identity without authentication.
6. The trusted CLI entrypoint is `python -m deployment.c3c.supervisor --request SIGNED.json --key KEY --principal OWNER --worker-image sha256:... --broker-image sha256:... --state PRIVATE_DIRECTORY`. No arbitrary command/image is accepted from an internet request. Execute only after separate infrastructure approval.
7. Install/review the external reaper service/timer outside job limits. It checks every 30 seconds plus scheduler/runtime delay; it is not an exact hard real-time guarantee. A host hang/runtime failure remains outside its guarantee. Test supervisor kill, reboot reconciliation and runtime outage. The reaper needs sensitive runtime authority; never give this authority to the public controller or jobs.
8. Complete `ACCEPTANCE.md`. Do not expose the example ingress (which returns 503) as a functioning service. A private authenticated controller, durable ownership-aware results API, bounded ingress and controlled report download integration still require implementation and acceptance. No anonymous or multi-tenant public service is enabled.

## Tests available now

`python -m unittest discover -s tests -p test_c3c_containment.py -v`

Tests distinguish mocked protocol/control flow from real Unix-socket integration. A skipped native/IPC test is NOT VERIFIED, not PASS. Do not infer OS isolation from configuration/readback alone. Existing C3B Windows acceptance remains separate and pending; the R2 Windows ZIP is unchanged.

## Authoritative references

- Docker resource constraints: https://docs.docker.com/engine/containers/resource_constraints/
- Docker network none (loopback remains): https://docs.docker.com/engine/network/drivers/none/
- NGINX TLS/mTLS configuration: https://nginx.org/en/docs/http/ngx_http_ssl_module.html
- OWASP SSRF prevention: https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
