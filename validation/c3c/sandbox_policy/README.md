# C3C narrow sandbox policy proposal

Status: **BLOCKED FOR A NATIVE WORKFLOW ATTEMPT**. This is a reviewed source-derived
proposal, not a verified compatible runtime correction. Nothing loads or attaches
these files. Existing workflows, application code and container arguments remain
unchanged. Do not push this directory expecting the existing run to exercise it.

Parent: `0df69f4b193ada03d655b9e0fc6129e605c918e9`.
Required main: `36c98ecd4537cc421e0ffe08321f62a10b0bed36`.

## Exact seccomp delta

The upstream Docker 28.0.4 JSON is retained byte-for-byte. The proposed profile
retains every syscall rule, condition, default EPERM action and clone3 ENOSYS rule.
Its architecture map is tightened to amd64 only, excluding x86 and x32. Exactly
five allow rules are appended:

| Syscall | Exact argument 0 | Purpose |
| --- | --- | --- |
| clone | `0x10000011` | Initial user-namespace prerequisite probe |
| clone | `0x70000011` | Full user/PID/network namespace zygote launch |
| clone | `0x20000011` | Nested PID namespace child after userns entry |
| unshare | `0x10000000` | Nested user namespace setup/probe |
| chroot | Path pointer cannot be filtered by classic seccomp | Chromium's safe empty filesystem-root sandbox |

The clone and unshare rules use **64-bit equality**, not namespace masks. No new
setns, mount, namespace combination, capability or clone3 allowance is introduced.
Partial zygote namespace combinations fail closed. Supported full user/PID/network
namespace availability is a requirement; there is no reduced-isolation fallback.

`chroot` is not privilege-granted by seccomp. The outer UID 10001 still has no
CAP_SYS_CHROOT. Chromium creates capabilities inside a *new user namespace*; these
are not capabilities in the host/container's parent user namespace. The proposal
requires the original empty outer capability set and NoNewPrivs=1; an independent
native check must confirm outer chroot denial and preservation of host boundaries.

## AppArmor delta

`chromium.apparmor` renders the pinned Docker 28.0.4 template as a separate named
**enforcing** profile. It preserves Docker's mount, proc/sys, firmware, securityfs,
signal and ptrace restrictions and standard base/tunables imports. It adds `userns,`
and requires AppArmor policy ABI 4.0. The daemon profile assumption is `unconfined`,
as an existing Docker signal peer, not an unconfined mode for the worker. If the
actual daemon is differently confined, stop and review that assumption.

This permission is necessarily coarse within the named worker profile: AppArmor
cannot express the clone flag equality constraints encoded by the paired seccomp
profile. All processes in the worker could attempt the allowed operations, not
only the Chromium executable. The pair must never be split. Seccomp continues to
bound namespace operations; AppArmor stays enforcing, and global restrictions and
`docker-default` are not changed. The effective host abstraction files and loaded
policy must be inspected before a native attempt: offline package imports do not
prove the host's imports match.

## Security trade-offs and independent boundaries

Allowing unprivileged user namespaces exposes additional kernel attack surface.
The proposal is therefore not security-equivalent to the original outer filter.
Its justification is enabling Chromium's inner namespace/filesystem/BPF sandbox
while retaining independent outer containment. No claim of a net security gain
or browser/kernel escape resistance is made from offline tests.

Required unchanged controls: host UID/GID 10001, NoNewPrivs=1, empty outer
capabilities, unprivileged container, read-only rootfs, network=none, private IPC,
1536 MiB memory/swap, one CPU, 64 PIDs, 256 MiB temporary storage and existing
ulimits/log limits. New network namespaces cannot attach to a host namespace:
setns remains denied, and no interfaces, host sockets or privileged mounts may be
provided. Cgroups are inherited and do not become writable. Broker/resource/API/
cleanup fixtures must remain on their existing policies and run unchanged.

## Verification performed

- 19 policy regression and negative-security tests passed.
- The proposed zero-capability amd64 profile compiled with local libseccomp to
  2736 bytes of classic BPF. A test interpreter evaluated that compiler output:
  the exact intended operations allow; extra namespace/control bits, setns,
  mount-family calls, kernel attack-surface calls and alternate ABIs deny.
- AppArmor syntax compiled offline with Ubuntu's signed-index-verified package
  `4.0.0-beta3-0ubuntu3`, package SHA256
  `d783c4183840745b931b72a9df8c15d341f640efa6f3069e5935c1b6542ff840`.
  Compilation used skip-kernel-load, skip-cache and explicit packaged ABI 4.0
  features/imports. The package was extracted in scratch, not installed. This is
  an offline syntax check, not approval of that old package for host installation.
- Original 45 focused tests and 11 workflow safety checks must also pass.
- No policy was loaded, no syscall filter was installed, no namespace was created,
  and no container, Chromium process or Actions run was started in this session.

Native enforcement, exact syscall errno, AppArmor contribution, mapped namespace
capabilities, outer chroot denial, UID/GID mappings, positive sandbox page,
Chromium integration and policy-specific kernel attack denials remain **NOT
VERIFIED**. Previous passing native checks are historical evidence for unchanged
code, not acceptance of this new policy.

## Remaining gate and minimum infrastructure capability

Before one workflow attempt is ready, provide a disposable amd64 Docker/cgroup-v2
Linux VM where an operator can load a separate named AppArmor 4 policy, inspect
its effective imports/ABI and capture bounded namespace/audit diagnostics. No
paid/larger runner requirement is established. Standard GitHub Ubuntu VMs may
supply these facilities; the actual availability is unverified here.

Prepare and review host preflight/attachment integration separately. It must
verify both policy hashes and exact effective container configuration, refuse
unsupported AppArmor ABI, perform bounded phase-specific namespace diagnostics,
and retain negative tests for namespace joining, mounts, outer chroot, network,
resource and cleanup boundaries. Do not silently substitute Docker defaults or
relax flags on failure. Do not disable AppArmor/seccomp or global userns controls,
add outer capabilities, enable root/privileged mode, share host networking/IPC,
change image/dependency pins or disable Chromium's sandbox.

## Primary sources

- Chromium 156.0.8078.4: `sandbox/linux/services/credentials.cc`,
  `namespace_sandbox.cc`, `namespace_utils.cc`, `sandbox/policy/linux/sandbox_linux.cc`
  and `content/browser/zygote_host/zygote_host_impl_linux.cc` under
  https://chromium.googlesource.com/chromium/src/+/156.0.8078.4/
- Docker 28.0.4 seccomp JSON and Go implementation:
  https://github.com/moby/moby/tree/v28.0.4/profiles/seccomp
- Docker 28.0.4 AppArmor template and loader:
  https://github.com/moby/moby/tree/v28.0.4/profiles/apparmor
- https://playwright.dev/python/docs/docker (general supported sandbox direction;
  its unrestricted namespace additions are not copied).
- https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces
- https://docs.kernel.org/userspace-api/no_new_privs.html

Upstream Docker files retain their original content; license in UPSTREAM-LICENSE.
