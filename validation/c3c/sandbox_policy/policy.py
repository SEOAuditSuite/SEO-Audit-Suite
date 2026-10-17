"""Offline policy proposal validation. Never loads a kernel policy or starts Docker."""
import copy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
BASE_HASH='9c1025c88ccaa517b648da571961838744ea2137f176bfe6a48b21294cae9c76'
APPARMOR_HASH='42130ca5908f45263facef820961d9e1a988e82f8a2937f4658e7bcccc96cc07'
PROFILE='c3c-chromium-userns-review'
NEWUSER=0x10000000
NEWPID=0x20000000
NEWNET=0x40000000
SIGCHLD=17
# Exact source-required operations, not a mask that accepts extra namespace flags.
CLONE_VALUES=(NEWUSER|SIGCHLD,NEWUSER|NEWPID|NEWNET|SIGCHLD,NEWPID|SIGCHLD)


def baseline():
    raw=(ROOT/'docker-28.0.4-default.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BASE_HASH:raise ValueError('Upstream seccomp checksum conflict')
    return json.loads(raw)


def build():
    policy=copy.deepcopy(baseline())
    # Restrict to the reviewed ABI; do not inherit x86/x32 compatibility syscalls.
    policy['archMap']=[dict(architecture='SCMP_ARCH_X86_64',subArchitectures=[])]
    for syscall,values in [('clone',CLONE_VALUES),('unshare',(NEWUSER,))]:
        for value in values:
            policy['syscalls'].append(dict(names=[syscall],action='SCMP_ACT_ALLOW',
                args=[dict(index=0,value=value,op='SCMP_CMP_EQ')],includes=dict(arches=['amd64'])))
    # Seccomp cannot dereference the pathname. Kernel CAP_SYS_CHROOT checks remain
    # mandatory: the outer zero-capability UID cannot use this before userns entry.
    policy['syscalls'].append(dict(names=['chroot'],action='SCMP_ACT_ALLOW',includes=dict(arches=['amd64'])))
    return policy


def apparmor():
    raw=(ROOT/'docker-28.0.4-apparmor-template.go').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=APPARMOR_HASH:raise ValueError('Upstream AppArmor checksum conflict')
    body=raw.decode().split('const baseTemplate = `\n',1)[1].rsplit('`',1)[0]
    body=body.replace('{{range $value := .Imports}}\n{{$value}}\n{{end}}','#include <tunables/global>')
    body=body.replace('{{range $value := .InnerImports}}\n  {{$value}}\n{{end}}','  #include <abstractions/base>\n  userns,')
    body=body.replace('{{.Name}}',PROFILE).replace('{{.DaemonProfile}}','unconfined')
    if '{{' in body:raise ValueError('Unresolved upstream template')
    return '# REVIEW PROPOSAL ONLY: not loaded or attached by this repository.\nabi <abi/4.0>,\n'+body


def validate(policy=None,profile=None):
    if policy is None:policy=json.loads((ROOT/'chromium-amd64.seccomp.json').read_text())
    if profile is None:profile=(ROOT/'chromium.apparmor').read_text()
    if policy!=build():raise ValueError('Policy differs from the exact reviewed delta')
    if profile!=apparmor():raise ValueError('AppArmor differs from preserved Docker template plus userns rule')
    return dict(status='PASS',scope='Exact proposal shape/checksums only; no native enforcement or compatibility claim')


if __name__=='__main__':print(json.dumps(validate(),sort_keys=True))
