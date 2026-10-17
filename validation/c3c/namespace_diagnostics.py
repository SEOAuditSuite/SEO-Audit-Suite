"""Bounded in-container prerequisite probes. No host policy writes or network use."""
import ctypes
import errno
import json
import os
from pathlib import Path
import signal
import time

NEWUSER=0x10000000
NEWPID=0x20000000
NEWNET=0x40000000


def failed(stage,code):return dict(stage=stage,status='FAIL',errno=code,error=errno.errorcode.get(code,'UNKNOWN'))


def namespace_child(lib,full=False):
    """Only the forked child writes its own uid/gid maps; outer UID remains 10001."""
    def mapping(uid,gid):
        Path('/proc/self/setgroups').write_text('deny')
        Path('/proc/self/uid_map').write_text('0 '+str(uid)+' 1')
        Path('/proc/self/gid_map').write_text('0 '+str(gid)+' 1')
    phase='uid_gid_mapping'
    try:
        mapping(10001,10001)
        if full:
            phase='zygote_pid_namespace'
            if os.getpid()!=1:return failed(phase,errno.EINVAL)
        phase='drop_child_capabilities'
        class Header(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
        class Data(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
        header=Header(0x20080522,0);caps=(Data*2)()
        if lib.capset(ctypes.byref(header),caps):return failed(phase,ctypes.get_errno())
        phase='nested_unshare_userns'
        if lib.unshare(NEWUSER):return failed(phase,ctypes.get_errno())
        # This mirrors Chromium's availability check, not a sandbox certification.
        return dict(stage='full_namespace_chain' if full else 'user_namespace_chain',status='PASS')
    except OSError as exc:return failed(phase,exc.errno)
    except Exception:return dict(stage=phase,status='FAIL',error='Unexpected probe exception')


def clone_probe(lib,flags,timeout=3):
    read_fd,write_fd=os.pipe();pid=-1;reaped=False
    try:
        ctypes.set_errno(0)
        pid=lib.syscall(ctypes.c_long(56),ctypes.c_ulong(flags),ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_ulong(0))
        if pid==-1:return failed('clone_'+hex(flags),ctypes.get_errno())
        if pid==0:
            os.close(read_fd)
            try:
                record=namespace_child(lib,full=flags==NEWUSER|NEWPID|NEWNET|signal.SIGCHLD)
                os.write(write_fd,json.dumps(record).encode()[:1024])
            finally:os._exit(0)
        os.close(write_fd);write_fd=None
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            done,status=os.waitpid(pid,os.WNOHANG)
            if done:
                reaped=True
                data=os.read(read_fd,1025)
                if len(data)>1024 or not os.WIFEXITED(status) or os.WEXITSTATUS(status)!=0:return dict(stage='namespace_child',status='FAIL',error='Invalid child exit/output')
                return json.loads(data)
            time.sleep(.01)
        return dict(stage='namespace_child',status='FAIL',error='Timeout')
    finally:
        if pid>0 and not reaped:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            os.waitpid(pid,0)
        os.close(read_fd)
        if write_fd is not None:os.close(write_fd)


def guard():
    if os.uname().machine!='x86_64':raise RuntimeError('Reviewed amd64 syscall ABI required')
    if Path('/proc/self/attr/current').read_text().strip()!='c3c-chromium-userns-review (enforce)':raise RuntimeError('Exact enforcing AppArmor label required')
    if not Path('/.dockerenv').is_file() or os.getuid()!=10001 or os.getgid()!=10001:raise RuntimeError('Non-root capped worker required for namespace probes')
    if len(list(Path('/proc/self/task').iterdir()))!=1:raise RuntimeError('Single-threaded namespace probe required')
    status=Path('/proc/self/status').read_text()
    values=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
    if values['Seccomp'].strip()!='2':raise RuntimeError('Seccomp filtering required')
    if values['NoNewPrivs'].strip()!='1' or any(int(values[name].strip(),16) for name in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')):raise RuntimeError('Outer privilege boundary differs')


def run_checks():
    guard()
    lib=ctypes.CDLL(None,use_errno=True);lib.syscall.restype=ctypes.c_long
    rows=[]
    # No valid namespace FD or mount target is supplied; these must fail closed.
    calls=[('setns_invalid_fd',lambda:lib.setns(-1,0)),
           ('mount_null_target',lambda:lib.mount(None,None,None,0,None)),
           ('outer_chroot',lambda:lib.chroot(b'/')),
           ('unshare_zero',lambda:lib.unshare(0)),
           ('unshare_mount_namespace',lambda:lib.unshare(0x20000))]
    for name,call in calls:
        ctypes.set_errno(0);result=call();code=ctypes.get_errno()
        rows.append(dict(stage=name,status='PASS' if result==-1 and code==errno.EPERM else 'FAIL',return_code=result,errno=code))
        if rows[-1]['status']!='PASS':break
    if all(row['status']=='PASS' for row in rows):
        for flags in (NEWUSER|signal.SIGCHLD,NEWUSER|NEWPID|NEWNET|signal.SIGCHLD):
            row=clone_probe(lib,flags);rows.append(row)
            if row['status']!='PASS':break
    record=dict(status='PASS' if all(row['status']=='PASS' for row in rows) else 'FAIL',checks=rows,
                scope='Temporary child user namespaces only; Chromium sandbox acceptance remains mandatory')
    print('C3C_NAMESPACE_DIAGNOSTIC '+json.dumps(record),flush=True)
    if record['status']!='PASS':raise RuntimeError('Namespace prerequisites or independent negative controls failed')
    return record
