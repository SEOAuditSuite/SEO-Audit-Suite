"""Bounded browser workers. Windows Jobs bound owned-tree resources; this is not whole-app isolation.

Workers must read stdin before launching descendants. Windows assigns a kill-on-
close Job Object before releasing that gate; POSIX uses a dedicated session.
"""
from dataclasses import dataclass, field
import os
import math
from pathlib import Path
import signal
import subprocess
import threading
import time

CLEANUP_SECONDS = 5
OUTPUT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class JobLimits:
    """Per-worker starting profile, requiring Windows/website calibration."""
    processes: int = 64
    memory_mib: int = 4096
    cpu_percent: int = 80

    def __post_init__(self):
        for name, low, high in [('processes', 2, 256), ('memory_mib', 64, 32768), ('cpu_percent', 1, 100)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Invalid worker resource limit: '+name)

    @classmethod
    def from_environment(cls):
        values = {}
        for name, key in [('processes','SEO_JOB_MAX_PROCESSES'), ('memory_mib','SEO_JOB_MEMORY_MIB'), ('cpu_percent','SEO_JOB_CPU_PERCENT')]:
            raw = os.environ.get(key)
            if raw is not None:
                if not raw.isascii() or not raw.isdecimal() or len(raw) > 6:
                    raise ValueError('Invalid worker resource configuration')
                values[name] = int(raw)
        return cls(**values)


def _worker_environment(environ=None):
    """Bootstrap paths only; do not mutate the parent or forward its credentials.

    Profile paths are compatibility inputs, not filesystem isolation. C3B/C3C
    resource and OS/network controls remain separate. Python executes from the
    explicit sys.executable used by callers; no inherited Python import hooks.
    """
    allowed = {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
        'TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA',
        'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432',
        'XDG_RUNTIME_DIR', 'XDG_CACHE_HOME', 'DISPLAY', 'WAYLAND_DISPLAY', 'LANG', 'LC_ALL',
        'PLAYWRIGHT_BROWSERS_PATH', 'PLAYWRIGHT_NODEJS_PATH',
    }
    source = os.environ if environ is None else environ
    result = {key:value for key,value in source.items() if key.upper() in allowed}
    # Fixed runtime settings replace, rather than inherit, Python configuration.
    result.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                  PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    return result


class WindowsJob:
    """Own only this worker tree, never the user's existing Chrome processes."""
    def __init__(self, process, policy=None):
        policy = policy or JobLimits.from_environment()
        import ctypes
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                ('Flags', w.DWORD), ('MinWS', ctypes.c_size_t), ('MaxWS', ctypes.c_size_t),
                ('ActiveLimit', w.DWORD), ('Affinity', ctypes.c_size_t),
                ('Priority', w.DWORD), ('Scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('Basic', Basic), ('IO', IO), ('ProcessMemory', ctypes.c_size_t),
                ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [('UserTime',ctypes.c_longlong),('KernelTime',ctypes.c_longlong),
                ('PeriodUser',ctypes.c_longlong),('PeriodKernel',ctypes.c_longlong),
                ('Faults',w.DWORD),('Total',w.DWORD),('Active',w.DWORD),('Terminated',w.DWORD)]
        self.ctypes, self.Accounting, self.Extended = ctypes, Accounting, Extended
        self.policy = policy
        self.port = None
        self.monitor_thread = None
        self.monitor_stop = threading.Event()
        self.resource_events = set()
        self.monitor_failed = False
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args in (
            ('CreateJobObjectW',[ctypes.c_void_p,w.LPCWSTR]),
            ('SetInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]),
            ('AssignProcessToJobObject',[w.HANDLE,w.HANDLE]),
            ('TerminateJobObject',[w.HANDLE,w.UINT]),
            ('QueryInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]),
            ('CloseHandle',[w.HANDLE])):
            fn=getattr(self.api,name); fn.argtypes=args; fn.restype=w.BOOL
        self.api.CreateJobObjectW.restype=w.HANDLE
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle: raise OSError('Worker Job Object unavailable')
        try:
            limits=Extended()
            limits.Basic.Flags=0x2000 | 0x8 | 0x200  # Kill-on-close, active processes, job commit.
            limits.Basic.ActiveLimit=policy.processes
            limits.JobMemory=policy.memory_mib * 1024 * 1024
            if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                raise OSError('Worker resource limits unavailable')
            self._resource_setup()
            if not self.api.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))):
                raise OSError('Worker Job Object assignment unavailable')
            self.monitor_thread=threading.Thread(target=self._monitor_resources,daemon=True)
            self.monitor_thread.start()
        except BaseException as exc:
            if isinstance(exc,(OSError,RuntimeError)):
                # Fixed internal stage only; never log URLs, commands or environments.
                label=str(exc)
                exc.resource_stage=label if label.startswith('Worker ') else 'Worker resource setup'
                exc.resource_os_error=getattr(ctypes,'get_last_error',lambda:0)()
            self.close()
            raise

    def _resource_setup(self):
        """Attach notifications before assignment; read back hard limits before stdin."""
        c=self.ctypes
        from ctypes import wintypes as w
        class Cpu(c.Structure):
            _fields_=[('Flags',w.DWORD),('Rate',w.DWORD)]
        class Port(c.Structure):
            _fields_=[('Key',c.c_void_p),('Port',w.HANDLE)]
        self.Cpu=Cpu
        for name,args,result in [
            ('CreateIoCompletionPort',[w.HANDLE,w.HANDLE,c.c_size_t,w.DWORD],w.HANDLE),
            ('GetQueuedCompletionStatus',[w.HANDLE,c.POINTER(w.DWORD),c.POINTER(c.c_size_t),c.POINTER(c.c_void_p),w.DWORD],w.BOOL)]:
            fn=getattr(self.api,name);fn.argtypes=args;fn.restype=result
        cpu=Cpu(0x1 | 0x4,self.policy.cpu_percent * 100)
        if not self.api.SetInformationJobObject(self.handle,15,c.byref(cpu),c.sizeof(cpu)):
            raise OSError('Worker CPU rate control unavailable')
        self.port=self.api.CreateIoCompletionPort(w.HANDLE(-1),None,0,1)
        if not self.port:raise OSError('Worker resource notifications unavailable')
        port=Port(1,self.port)
        if not self.api.SetInformationJobObject(self.handle,7,c.byref(port),c.sizeof(port)):
            raise OSError('Worker resource notification assignment unavailable')
        info=self.resource_snapshot()
        if not info.get('verified'):
            raise OSError('Worker resource limit readback failed')

    def resource_snapshot(self):
        c=self.ctypes
        limits=self.Extended();cpu=self.Cpu();account=self.Accounting()
        queries=[self.api.QueryInformationJobObject(self.handle,k,c.byref(v),c.sizeof(v),None)
                 for k,v in [(9,limits),(15,cpu),(1,account)]]
        verified=all(queries) and limits.Basic.Flags & 0x2208 == 0x2208 and not limits.Basic.Flags & 0x1800
        verified=bool(verified and limits.Basic.ActiveLimit==self.policy.processes
            and limits.JobMemory==self.policy.memory_mib * 1024 * 1024
            and cpu.Flags==5 and cpu.Rate==self.policy.cpu_percent * 100)
        return dict(verified=verified,process_limit=int(limits.Basic.ActiveLimit),
            committed_memory_limit_bytes=int(limits.JobMemory),peak_job_memory_bytes=int(limits.PeakJob),
            cpu_rate_percent=int(cpu.Rate)/100,cpu_flags=int(cpu.Flags),limit_flags=int(limits.Basic.Flags),
            job_cpu_seconds=(int(account.UserTime)+int(account.KernelTime))/10000000,
            total_processes=int(account.Total),terminated_processes=int(account.Terminated),
            limit_events=sorted(self.resource_events),monitor_failed=self.monitor_failed)

    def _monitor_resources(self):
        # Completion messages are advisory (Microsoft does not guarantee delivery).
        # A confirmed memory/process event invalidates output, never invents HTTP status.
        c=self.ctypes
        from ctypes import wintypes as w
        try:
            while not self.monitor_stop.is_set():
                msg=w.DWORD();key=c.c_size_t();overlapped=c.c_void_p()
                ok=self.api.GetQueuedCompletionStatus(self.port,c.byref(msg),c.byref(key),c.byref(overlapped),50)
                if not ok:
                    if c.get_last_error()==258:continue  # WAIT_TIMEOUT
                    raise OSError('Resource notification read failed')
                if key.value!=1:raise OSError('Unexpected resource notification key')
                if msg.value in (3,9,10):
                    self.resource_events.add({3:'active_process_limit',9:'process_memory_limit',10:'job_memory_limit'}[msg.value])
                    self.terminate()
        except Exception:
            self.monitor_failed=True
            self.terminate()

    def terminate(self):
        return bool(self.api.TerminateJobObject(self.handle,1))

    def empty(self):
        info=self.Accounting()
        if not self.api.QueryInformationJobObject(self.handle,1,self.ctypes.byref(info),self.ctypes.sizeof(info),None):
            return False
        return info.Active == 0

    def snapshot(self):
        """Bounded membership evidence from this exact Job, without command lines."""
        from ctypes import wintypes as w
        info=self.Accounting()
        if not self.api.QueryInformationJobObject(self.handle,1,self.ctypes.byref(info),self.ctypes.sizeof(info),None):
            return dict(available=False)
        class Pids(self.ctypes.Structure):
            _fields_=[('Assigned',w.DWORD),('Listed',w.DWORD),('Ids',self.ctypes.c_size_t*1024)]
        ids=Pids()
        listed=bool(self.api.QueryInformationJobObject(self.handle,3,self.ctypes.byref(ids),self.ctypes.sizeof(ids),None))
        return dict(available=True,active_processes=int(info.Active),membership_available=listed,
            pids=[int(ids.Ids[i]) for i in range(min(ids.Listed,1024))] if listed else [],
            membership_complete=listed and ids.Listed<=1024 and ids.Assigned==ids.Listed,
            resources=self.resource_snapshot())

    def close(self):
        self.monitor_stop.set()
        if self.monitor_thread is not None:
            self.monitor_thread.join(timeout=1)
            if self.monitor_thread.is_alive():self.monitor_failed=True
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle=None
        if self.port and not (self.monitor_thread and self.monitor_thread.is_alive()):
            self.api.CloseHandle(self.port); self.port=None


def _host_group(pid):
    """Map a new worker's namespace PID while it is still behind the stdin gate."""
    if not isinstance(pid,int) or not Path('/proc').is_dir(): return None
    try:
        namespace=os.readlink('/proc/self/ns/pid')
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit(): continue
            try:
                if os.readlink(entry/'ns/pid') != namespace: continue
                rows=dict(line.split(':',1) for line in (entry/'status').read_text().splitlines() if ':' in line)
                if int(rows.get('NSpid',rows['Pid']).split()[-1]) == pid:
                    return int((entry/'stat').read_text().rsplit(')',1)[1].split()[2])
            except (FileNotFoundError, ProcessLookupError, PermissionError): pass
    except (OSError, ValueError, IndexError): pass
    return None


def _group_empty(pid, host_group=None):
    """Linux zombies cannot execute; other POSIX systems use conservative probing."""
    if Path('/proc').is_dir() and isinstance(host_group,int):
        try:
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit(): continue
                try:
                    fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    if int(fields[2]) == host_group and fields[0] != 'Z': return False
                except (FileNotFoundError, ProcessLookupError): pass
            return True
        except (OSError, ValueError, IndexError): return False
    try: os.killpg(pid,0); return False
    except ProcessLookupError: return True
    except OSError: return False


class LinuxTree:
    """Track owned descendants, including Playwright's detached Chrome group.

    Host PID/start-time pairs prevent signalling reused or unrelated PIDs. This
    is cleanup for ordinary descendants, not containment of a compromised fork.
    """
    def __init__(self, host_pid):
        self.root=host_pid; self.owned={}; self.groups={}; self.failed=False
        self.depth=len(next(line for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('NSpid:')).split()[1:])-1
        self.stopped=threading.Event()
        self.scan()
        self.thread=threading.Thread(target=self.monitor,daemon=True)
        self.thread.start()

    def rows(self):
        rows={}
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():continue
            try:
                fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                data=dict(line.split(':',1) for line in (entry/'status').read_text().splitlines() if ':' in line)
                pids=data.get('NSpid',data['Pid']).split()
                groups=data.get('NSpgid','').split()
                if len(pids)<=self.depth or len(groups)<=self.depth:continue
                rows[int(entry.name)]=(int(fields[1]),fields[0],fields[19],int(pids[self.depth]),int(groups[self.depth]),int(fields[2]))
            except (FileNotFoundError,ProcessLookupError):pass
            except (OSError,ValueError,IndexError,KeyError):
                # Cannot certify an owned process if its proc entry is inaccessible.
                if int(entry.name) in self.owned:self.failed=True
        return rows

    def scan(self):
        try:
            rows=self.rows()
            if self.root in rows and self.root not in self.owned:
                self.owned[self.root]=rows[self.root]
            parents={pid for pid,row in self.owned.items() if pid in rows and rows[pid][2]==row[2]}
            changed=True
            while changed:
                changed=False
                for pid,row in rows.items():
                    if row[0] in parents and pid not in parents:
                        parents.add(pid);self.owned[pid]=row;changed=True
            for pid in parents:
                row=self.owned[pid]
                if row[4]>1:self.groups[row[4]]=row[5]
        except (OSError,ValueError):self.failed=True

    def monitor(self):
        while not self.stopped.wait(0.05):self.scan()

    def stop(self):
        self.stopped.set();self.thread.join(timeout=1)
        if self.thread.is_alive():self.failed=True
        else:self.scan()

    def kill(self):
        current=self.rows()
        for local,host in list(self.groups.items()):
            owned=any(pid in current and current[pid][2]==row[2] and current[pid][1]!='Z' and current[pid][5]==host
                      for pid,row in self.owned.items())
            if owned:
                try:os.killpg(local,signal.SIGKILL)
                except ProcessLookupError:pass
                except OSError:self.failed=True
        # A descendant can establish another group after the last scan.
        for host,row in list(self.owned.items()):
            try:
                fields=(Path('/proc')/str(host)/'stat').read_text().rsplit(')',1)[1].split()
                if fields[19]==row[2] and fields[0]!='Z' and row[3]>1:os.kill(row[3],signal.SIGKILL)
            except (FileNotFoundError,ProcessLookupError):pass
            except (OSError,ValueError,IndexError):self.failed=True

    def empty(self):
        if self.failed:return False
        if any(not _group_empty(local,host) for local,host in self.groups.items()):return False
        rows=self.rows()
        return not self.failed and all(pid not in rows or rows[pid][2]!=row[2] or rows[pid][1]=='Z' for pid,row in self.owned.items())


def cleanup_tree(process, job=None):
    """Never lets a second communicate/wait timeout escape. Returns confirmation."""
    confirmed=False
    started=time.monotonic()
    details=dict(method='windows_job' if job is not None else 'windows_gated_worker' if os.name=='nt' else 'linux_owned_tree',
                 before=None,after=None,confirmed=False)
    process._seo_cleanup_details=details
    def capture():
        if job is not None:
            try:
                value=job.snapshot()
                return value if isinstance(value,dict) else None
            except Exception:return dict(available=False)
        return None
    tree=getattr(process,'_seo_tree',None)
    tree=tree if isinstance(tree,LinuxTree) else None
    try:
        if not isinstance(process.pid, int) or process.pid <= 1:
            return False  # Never signal a malformed PID or the host's init group.
        if tree is not None:tree.stop()
        details['before']=capture()
        if job is not None:
            terminated=job.terminate()
        elif os.name == 'nt':
            # Job assignment failed before stdin gate release; no browser launched.
            terminated=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=CLEANUP_SECONDS).returncode == 0
        else:
            if tree is not None:tree.kill()
            else:
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
            terminated=True
        try: process.kill()
        except OSError: pass
        try: process.communicate(timeout=CLEANUP_SECONDS)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            # Inherited pipes may never produce EOF; no further unbounded drain.
            return False
        end=time.monotonic()+1
        while True:
            empty=job.empty() if job is not None else process.poll() is not None if os.name == 'nt' else tree.empty() if tree is not None else _group_empty(process.pid,getattr(process,'_seo_host_group',None))
            if empty or time.monotonic()>=end:
                confirmed=bool(terminated and empty and (os.name=='nt' or tree is not None)); break
            time.sleep(0.02)
    except (OSError, subprocess.TimeoutExpired):
        try: process.kill()
        except OSError: pass
        try: process.wait(timeout=CLEANUP_SECONDS)
        except (OSError, subprocess.TimeoutExpired): pass
    finally:
        details.update(after=capture(),confirmed=confirmed,seconds=round(time.monotonic()-started,6))
        if tree is not None:tree.stopped.set()
        if job is not None: job.close()
    return confirmed


@dataclass
class WorkerResult:
    output: str = ''
    reason: str = ''
    cleanup_confirmed: bool = False
    diagnostics: dict = field(default_factory=dict)


def run_worker(command, payload, seconds, limits=None):
    """Hard deadline includes worker startup, transport, rendering and normal close."""
    if not isinstance(seconds,(int,float)) or isinstance(seconds,bool) or not math.isfinite(seconds) or not 0 < seconds <= 600:
        return WorkerResult(reason='invalid_execution_deadline')
    try:
        policy=limits if limits is not None else JobLimits.from_environment()
        if not isinstance(policy,JobLimits):raise ValueError('Invalid policy')
    except (ValueError,TypeError):
        return WorkerResult(reason='invalid_resource_policy')
    started=time.monotonic()
    flags={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
    try:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=_worker_environment(),**flags)
    except OSError: return WorkerResult(reason='worker_start_failed')
    job=None; result=WorkerResult(); setup_failure=None
    try:
        if os.name=='nt': job=WindowsJob(process, policy) if limits is not None else WindowsJob(process)
        else:
            process._seo_host_group=_host_group(process.pid)
            if isinstance(process._seo_host_group,int) and Path('/proc').is_dir():
                process._seo_tree=LinuxTree(process._seo_host_group)
        output,_=process.communicate(payload,timeout=max(0.001,seconds-(time.monotonic()-started)))
        if process.returncode: result.reason='worker_crashed'
        elif len(output.encode('utf-8')) > OUTPUT_BYTES: result.reason='worker_output_limit'
        else: result.output=output
    except subprocess.TimeoutExpired:
        result.reason='execution_deadline'
    except (OSError, ValueError, RuntimeError) as exc:
        result.reason='worker_setup_or_io_failed'
        if isinstance(getattr(exc,'resource_stage',None),str):
            setup_failure=dict(stage=exc.resource_stage,winerror=exc.resource_os_error)
    finally:
        # Runs for success, failure, KeyboardInterrupt and cancellation alike.
        result.cleanup_confirmed=cleanup_tree(process,job)
        if job is not None:
            if isinstance(getattr(job,'resource_events',None),set) and job.resource_events:
                result.reason='resource_limit';result.output=''
            elif getattr(job,'monitor_failed',False) is True:
                result.reason='resource_monitor_unavailable';result.output=''
        cleanup=getattr(process,'_seo_cleanup_details',None)
        result.diagnostics=dict(worker_pid=process.pid if isinstance(process.pid,int) else None,
            platform=os.name,deadline_seconds=seconds,elapsed_seconds=round(time.monotonic()-started,6),
            stop_reason=result.reason,returncode=process.returncode if isinstance(process.returncode,int) else None,
            cleanup=cleanup if isinstance(cleanup,dict) else None)
    if setup_failure is not None:result.diagnostics['resource_setup_failure']=setup_failure
    if not result.cleanup_confirmed and not result.reason: result.reason='cleanup_unconfirmed'
    result.diagnostics['stop_reason']=result.reason
    return result
