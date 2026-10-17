# C3C Application Integration — Current Engineering Instructions

This document supersedes the missing-controller/build descriptions in the preserved engineering-preview README. All original 20 additive files and the complete ten-file C3B R2 patch remain byte-identical. **Public deployment and GitHub publication remain on hold.** Windows C3B native acceptance is a separate unresolved gate; its 1536-MiB preflight is unchanged.

## Implemented path

Reviewed mTLS HTTPS gateway -> private Unix-socket controller -> signed durable bounded SQLite queue -> external agent -> existing supervisor -> network-none disposable audit job -> read-only socket capability -> separate C1 GET broker. The job invokes the original audit/report pipeline; browser requests never receive an unrestricted native network fallback. The controller has no container-runtime authority. The agent revalidates the job's owner/signature/expiry before execution, and only operator-configured immutable images and fixed budgets can run.

The initial controlled API accepts URL plus 1-10 pages. Local Streamlit, optional Phase 2/3 diagnostics, scoring and nine exports remain intact; optional diagnostics and CSV uploads are not exposed as additional public API operations in this minimum profile. The preserved Phase 3 transport still imports the image-only bridge and retains its same-origin restrictions. Real image integration remains a native gate.

## Authentication and authorization

Every API request requires HMAC authentication bound to owner, exact method/path, body SHA-256, timestamp and one-use request nonce. Each owner has an independent 32-byte key. There is also a separate owner-bound signed job envelope with a one-use job ID and maximum 300-second admission lifetime. Authentication request window is 60 seconds past / 10 seconds future. Replay records persist across controller restarts. Queue expiry is rechecked before launch, so an expired waiting job does not run.

The gateway requires a dedicated mTLS client CA; HMAC owner keys independently identify/authorize each owner. A valid CA client certificate alone cannot choose another owner. Use `ingress-integrated.conf.example`, not the older intentionally-503 gateway template. Do not expose raw Streamlit or the Unix socket. WebSockets are not used by this API; upgrades are stripped. CORS/XSRF policies are not disabled.

Provision `/etc/seo-control/owners.json` as a restricted JSON map of owner identifiers to 64-character lowercase hex keys (32 random bytes each), mode 0640 root:seo-control. Do not reuse keys between owners. Only controller and trusted agent can read it; the gateway, browser/job and broker cannot. Individual client key files contain the owner's hex key and must be mode 0600. Never pass keys through URLs, CLI string arguments, worker environment variables or Docker build arguments. No keys were generated or installed by this package.

API:

| Method/path | Result |
|---|---|
| POST /v1/jobs | Signed job admission; 202, or bounded-capacity 429 |
| GET /v1/jobs/ID | Owner-only status/cleanup and artifact names; no raw URL/body |
| DELETE /v1/jobs/ID | Owner-only cancellation; active jobs remain cancelling until cleanup |
| GET /v1/jobs/ID/artifacts/NAME | Owner-only bounded attachment, no inline active HTML |

Cross-owner and unknown IDs both return 404. Authentication failure returns 401. Framing rejects duplicate authentication/length headers and Transfer-Encoding. Input is at most 16 KiB. A five-second request timer aborts stalled/slow requests; actual socket interruption must be validated natively. Public ingress is additionally rate/connection limited.

## Queue, storage and cancellation

One agent operation at a time; two waiting jobs. The controller processes requests serially with a bounded socket backlog. A per-owner 60-request/minute limit and maximum 4096 retained request nonces prevent unbounded authentication tables. At most 32 retained job records, 24-hour completed retention and output-capacity reservation limit admission. SQLite uses a 64-MiB page ceiling with DELETE journaling; host filesystem quotas must cover database/journal/output overhead independently. These are controlled-launch limits, not measured production capacity.

Cancellation is durable. Queued jobs are cancelled without launch; an active agent checks cancellation through the supervisor deadline path, including the browser wait loop. Cleanup commands deliberately bypass the cancellation flag, retain their own bounded timeouts and must prove no owned survivors. Cleanup uncertainty quarantines admission and blocks artifacts. Agent restart detects interrupted operations and quarantines rather than rerunning them. Do not assume a cancelled UI request proves native cleanup.

After the external reaper and operator verify cleanup, `python -m deployment.c3c.agent ... --reconcile` checks that no managed containers or owned IPC volumes remain before clearing queue/supervisor quarantine. This is a privileged operational action, not a client API. Expiry reaper timers remain required; controller/agent/kernel/runtime failures require independent infrastructure testing.

## Reproducible build inputs

`requirements.linux.lock` pins the full 41-package dependency closure for Linux amd64 CPython 3.12 with SHA-256 hashes of actual recovered wheel bytes. Its versions satisfy the existing project requirements; requirements.txt is unchanged. This is a reproducible dependency lock, not a vulnerability audit or native image acceptance.

`browser-revisions.json` records the exact browser revisions bundled with the pinned Playwright package. Supply a reviewed official Playwright Python base matching that version, Python 3.12 and amd64, **pinned by a real registry digest**. No base digest is invented or silently selected. The target host must obtain/verify that digest. `build_verify.py` checks version and matching executable presence at build time; it does not certify a sandbox launch. No apt install or browser download is performed inside the build: Chromium/OS content comes from the pinned base. Dependency wheels are installed offline with --require-hashes.

Build preparation command, run from the verified source copy:

```
python -m deployment.c3c.prepare_build --source . --manifest SOURCE-MANIFEST.json --output NEW_PRIVATE_CONTEXT --download-wheels
```

This verifies every source hash before creating a sanitized context. Only manifest-listed files are eligible; repository history, tests, private keys and local environments are excluded. The downloader uses exact pinned hashes and a fixed HTTPS package index; wheel download is a separate trusted provisioning step, not worker runtime egress. Do not build if a wheel/digest is unavailable or mismatched. There is no unpinned fallback.

In that context, after infrastructure approval:

```
docker build --platform linux/amd64 --build-arg BASE_IMAGE=REVIEWED_IMAGE@sha256:REAL_DIGEST -f deployment/c3c/Dockerfile.integrated --target worker -t seo-c3c-worker:test .
docker build --platform linux/amd64 --build-arg BASE_IMAGE=REVIEWED_IMAGE@sha256:REAL_DIGEST -f deployment/c3c/Dockerfile.integrated --target broker -t seo-c3c-broker:test .
```

Record local immutable image IDs; agent execution accepts those IDs, not tags. Never disable the Chromium sandbox, TLS verification, C1 policy or network restrictions to resolve a launch failure. Non-root sandbox/user-namespace/seccomp compatibility must pass on the actual host. Shared-kernel containers do not establish protection against all browser/kernel exploits.

## One acceptance procedure (isolated Linux only)

1. Verify consolidated package manifest and exact baseline/R2/preview hashes. Use a disposable Linux VM with cgroup v2, sufficient measured headroom, Docker, firewall authority and no unrelated secrets. Keep all public ports closed. No VM, hosting or infrastructure is created by these files.
2. Create a fresh Python 3.12 venv. Install the pinned lock with pip --require-hashes. Run `sh START-LINUX-ACCEPTANCE.sh --output NEW_EVIDENCE_DIRECTORY`. It runs the full regression suite and records unsupported native gates as NOT VERIFIED; it does not configure the host. Do not treat a zero regression exit code with skipped tests as complete native acceptance.
3. Obtain the pinned base digest, prepare/build reviewed images, provision separate service users/ACLs and quota-limited database/supervisor/artifact storage. Review `controller.service.example` and `agent.service.example` before installation. The controller must not belong to the docker group; only the dedicated external supervisor does. Signing keys and mTLS secrets must never enter the job images or mounts.
4. Implement/test the dedicated broker bridge and reviewed IPv4/IPv6/host/metadata firewall rules from the original acceptance checklist. Preserve independent default-deny enforcement. The network label is only an operational guard. Prove denial with reachable controlled canaries and packet/firewall evidence, not failed connections to absent services.
5. In the isolated environment start the private controller and separate agent using the supplied service arguments, plus the external reaper. Use an internal test TLS gateway or loopback-only port forwarding; do not open public ingress. Validate signed submission/status/download/cancel through real HTTP over the Unix socket and mTLS gateway. `client.py --endpoint https://INTERNAL_TEST_HOST --owner OWNER --key OWNER_KEY --ca CA --cert CERT --cert-key CERT_KEY --url CONTROLLED_FIXTURE_URL` supplies a correctly signed request without proxy inheritance. Use --job ID, --cancel, or --artifact NAME --output NEW_FILE for follow-up operations. No existing output is overwritten.
6. Run actual native resource fixtures with `sh START-LINUX-ACCEPTANCE.sh --output NEW_NATIVE_EVIDENCE_DIRECTORY --native --worker-image sha256:REVIEWED_ID`. Fixtures are serial with small hard caps and deadlines. Review resource counters and zero-owned-survivor evidence. Separate raw network, gateway, cancellation/reaper and Chromium gates remain mandatory; the launcher does not automatically certify them.
7. Use owned controlled public-address HTTP fixtures for JS links/content, CDN/redirect handling and attempted forbidden resources; do not relax C1 to permit private fixtures. Compare original scores/nine exports on identical evidence, verify unknown/partial rendering, inspect desktop/mobile reports and credentials/filesystem boundaries. Preserve Phase 3 same-origin behavior. Windows screenshots do not certify this Linux environment.
8. Review every PASS/FAIL/NOT VERIFIED record and evidence hash. The launcher produces `NEW_EVIDENCE_DIRECTORY-Evidence.zip`. Add independent firewall/canary captures, real API/browser results and image/policy identities. Only after all essential gates pass, and separate C3B Windows acceptance is reviewed, request GitHub publication approval. Deployment requires its own later approval.

Launcher exit code 1 means regression failure; exit code 2 means acceptance remains NOT VERIFIED (including successful regressions with pending native gates). Evidence is packaged in both cases. A generated ZIP or normal resource-fixture completion is not a public-security acceptance certificate.

## Current limits

Application integration and deterministic tests are implemented. Native Docker, Unix IPC, cgroups, firewall, mTLS, Chromium sandbox, cancellation and external cleanup remain unverified where unavailable in Work. No public deployment readiness is claimed. Existing local auditing remains separate from public service acceptance.
