"""Synthetic native acceptance probe. Run only in the capped worker container."""
import json
import os
from pathlib import Path
import re
import resource
import sys
import contextlib
import select
import threading
import time


sys.path.insert(0,'/app')



def sanitize(value, limit=3072):
    """Redact before truncating; never emit arbitrary environment or raw tracebacks."""
    value=str(value)
    value=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value)
    value=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)', '[REDACTED KEY]', value, flags=re.S)
    value=re.sub(r'(?i)(https?://)[^/\s@]+@', r'\1[REDACTED]@', value)
    value=re.sub(r'(https?://[^\s?#]+)[?#][^\s]*', r'\1?[REDACTED]', value)
    value=re.sub(r'(?im)(authorization\s*[:=]\s*)[^\r\n]+', r'\1[REDACTED]', value)
    value=re.sub(r"(?i)((?:password|passwd|secret|token|api[_-]?key)[\"']?\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r'\1[REDACTED]', value)
    value=''.join(c for c in value if c in '\n\t' or ord(c)>=32 and ord(c)!=127)
    return value[:limit]+(' [TRUNCATED]' if len(value)>limit else '')


def emit(kind, **fields):
    print('C3C_BROWSER_DIAGNOSTIC '+json.dumps(dict(kind=kind, **fields)), flush=True)


def exit_evidence(message):
    match=re.search(r'process did exit: exitCode=([^,>]+), signal=([^>]+)', message)
    return dict(exit_code=match.group(1).strip() if match else None,
                signal=match.group(2).strip() if match else None,
                status='OBSERVED' if match else 'NOT VERIFIED')


class ObservedChromium:
    """Observe the existing launch attempts without modifying options or exceptions."""
    def __init__(self, target, progress=None): self.target=target;self.progress=progress
    def __getattr__(self, name): return getattr(self.target, name)
    def launch(self, **kwargs):
        attempt='system_chrome' if kwargs.get('channel')=='chrome' else 'pinned_chromium'
        if self.progress is not None:
            kwargs['timeout']=min(kwargs.get('timeout',30000),self.progress.remaining_ms())
        try:
            browser=self.target.launch(**kwargs)
            emit('launch', attempt=attempt, status='STARTED')
            return browser
        except Exception as exc:
            chain=[];current=exc;seen=set()
            while current is not None and id(current) not in seen and len(chain)<4:
                seen.add(id(current));chain.append(type(current).__name__+': '+str(current))
                current=current.__cause__ or (None if current.__suppress_context__ else current.__context__)
            message='\nCaused by: '.join(chain)
            emit('launch', attempt=attempt, status='FAIL', exception_type=type(exc).__name__,
                 exception=sanitize(message), process=exit_evidence(message))
            raise


class ObservedPlaywright:
    def __init__(self, target, progress=None):
        self.target=target; self.chromium=ObservedChromium(target.chromium,progress)
    def __getattr__(self, name): return getattr(self.target, name)


@contextlib.contextmanager
def driver_diagnostics():
    """Exact SDK driver inherits fd 2. Drain continuously; keep only sanitized bounded lines."""
    previous=os.environ.get('DEBUG'); saved=os.dup(2); read_fd,write_fd=os.pipe()
    stop=threading.Event(); retained=[]; size=0; truncated=False
    def drain():
        nonlocal size,truncated
        pending=b''; dropping=False; private=False
        def line(raw):
            nonlocal size,truncated,private
            text=raw.decode('utf-8',errors='replace')
            if '-----BEGIN ' in text and 'PRIVATE KEY-----' in text: private=True
            if private:
                if '-----END ' in text and 'PRIVATE KEY-----' in text: private=False
                text='[REDACTED KEY]'
            cleaned=sanitize(text,4096)+'\n'
            retained.append(cleaned);size+=len(cleaned)
            while size>8192 and retained:
                size-=len(retained.pop(0));truncated=True
        try:
            while True:
                ready,_,_=select.select([read_fd],[],[],.05)
                if not ready:
                    if stop.is_set(): break
                    continue
                chunk=os.read(read_fd,4096)
                if not chunk: break
                for part in chunk.splitlines(keepends=True):
                    ending=part.endswith(b'\n')
                    if not dropping:
                        pending+=part[:max(0,4096-len(pending))]
                        if len(pending)>=4096: dropping=True;truncated=True
                    if ending:
                        line(pending);pending=b'';dropping=False
            if pending:line(pending)
        finally: os.close(read_fd)
    thread=threading.Thread(target=drain,daemon=True)
    try:
        os.environ['DEBUG']='pw:browser'
        thread.start();os.dup2(write_fd,2);os.close(write_fd);write_fd=None
        def report():
            emit('driver_stderr', text=''.join(list(retained))[-8192:], truncated=truncated,
                 capture_complete=False, limit_characters=8192)
        yield report
    finally:
        os.dup2(saved,2);os.close(saved)
        if write_fd is not None:os.close(write_fd)
        if previous is None:os.environ.pop('DEBUG',None)
        else:os.environ['DEBUG']=previous
        stop.set();thread.join(timeout=2)
        emit('driver_stderr', text=''.join(retained), truncated=truncated,
             capture_complete=not thread.is_alive(), limit_characters=8192)


def process_snapshot(root=Path('/proc')):
    """Container-local allowlist: no command lines, environments, URLs or host scans."""
    rows=[]
    try:
        for item in root.iterdir():
            if not item.name.isdigit():continue
            if len(rows)>=64:break
            row={'pid':int(item.name)}
            try:
                with (item/'status').open() as stream:raw=stream.read(8192)
                for key in ('Name','State','PPid','Threads','NoNewPrivs','Seccomp'):
                    match=re.search(r'^'+key+r':\s*(.*)$',raw,re.M)
                    if match:row[key]=sanitize(match[1],96)
                with (item/'wchan').open() as stream:row['wchan']=sanitize(stream.read(128),128)
            except OSError:row['status']='NOT VERIFIED'
            rows.append(row)
    except OSError:return {'status':'NOT VERIFIED','processes':rows}
    return {'status':'OBSERVED','processes':rows,'maximum':64,
            'observed_process_count':len(rows),
            'observed_thread_count':sum(int(row.get('Threads','0')) for row in rows if str(row.get('Threads','0')).isdigit()),
            'complete':len(rows)<64 and all('Threads' in row for row in rows),
            'interpretation':'Racy PID namespace snapshot; not a peak or host UID task total'}


RESOURCE_FILES = ('pids.current','pids.max','pids.peak','pids.events','pids.events.local',
                  'memory.current','memory.max','memory.peak','memory.events','memory.events.local')


def numeric_read(path, limit=1024):
    """Strict numeric allowlist; no arbitrary file contents or unknown-as-zero."""
    try:
        with path.open() as stream:raw=stream.read(limit+1)
        if len(raw)>limit:return 'NOT VERIFIED: oversized'
        raw=raw.strip()
        if re.fullmatch(r'(?:[0-9]+|max)',raw):return raw
        rows=raw.splitlines()
        if rows and all(re.fullmatch(r'[a-z_]+ [0-9]+',row) for row in rows):
            return dict(row.split() for row in rows)
        return 'NOT VERIFIED: malformed'
    except OSError:return 'NOT VERIFIED: unavailable'


def task_resources(cgroup=Path('/sys/fs/cgroup'), proc=Path('/proc')):
    """Synchronous reads only: adds no worker threads/processes or security changes.

    Private cgroup/PID namespaces hide ancestors and per-UID host task totals.
    Snapshot counts can miss short peaks; counter deltas are stronger evidence.
    """
    readings={name:numeric_read(cgroup/name) for name in RESOURCE_FILES}
    limits={}
    for name in ('NPROC','STACK','AS','NOFILE','CORE'):
        try:limits[name]=list(resource.getrlimit(getattr(resource,'RLIMIT_'+name)))
        except (OSError,ValueError):limits[name]='NOT VERIFIED'
    host={name:numeric_read(proc/'sys/kernel'/name) for name in ('threads-max','pid_max')}
    # Host aggregate scheduler task total, not PID/UID attribution or commands.
    try:
        with (proc/'loadavg').open() as stream:raw=stream.read(256)
        field=raw.split()[3]
        host['scheduler_tasks']=field if re.fullmatch(r'[0-9]+/[0-9]+',field) else 'NOT VERIFIED'
    except (OSError,IndexError):host['scheduler_tasks']='NOT VERIFIED'
    try:
        with (proc/'meminfo').open() as stream:raw=stream.read(8192)
        host['memory_kib']={key:int(value) for key,value in re.findall(
            r'^(MemAvailable|CommitLimit|Committed_AS):\s+([0-9]+) kB$',raw,re.M)}
    except OSError:host['memory_kib']='NOT VERIFIED'
    space={}
    for path in ('/tmp','/dev/shm'):
        try:
            st=os.statvfs(path);space[path]={'available_bytes':st.f_bavail*st.f_frsize,'available_inodes':st.f_favail}
        except OSError:space[path]='NOT VERIFIED'
    tasks=process_snapshot(proc)
    counts={key:tasks.get(key,'NOT VERIFIED') for key in ('observed_process_count','observed_thread_count','complete')}
    return dict(cgroup=readings,launcher_rlimits=limits,host=host,space=space,namespace_task_counts=counts,
                ancestor_limits='NOT VERIFIED',host_uid_task_total='NOT VERIFIED')


def event_delta(before, after, name):
    """No denial attribution from EAGAIN, missing data, equality or counter reset."""
    a=before.get('cgroup',{}).get(name);b=after.get('cgroup',{}).get(name)
    if not isinstance(a,dict) or not isinstance(b,dict):return 'NOT VERIFIED'
    if set(a)!=set(b):return 'NOT VERIFIED'
    try:
        result={key:int(b[key])-int(a[key]) for key in a}
        return result if all(v>=0 for v in result.values()) else 'NOT VERIFIED: counter reset'
    except (TypeError,ValueError):return 'NOT VERIFIED'


class ProbeDeadline:
    """Hard stop for synchronous APIs lacking timeout options; parent owns cleanup.

    Started only after the single-threaded negative namespace checks. The 34s
    absolute budget starts at probe entry, inside the unchanged 40s Docker budget.
    """
    def __init__(self, started, stderr, total=34, terminate=os._exit):
        self.started=started;self.deadline=started+total;self.stderr=stderr
        self.terminate=terminate;self.stop=threading.Event();self.lock=threading.Lock()
        self.name='post_namespace';self.phase_deadline=self.deadline
        self.resource_baseline={}
        self.thread=threading.Thread(target=self.watch,daemon=True)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*exc):self.stop.set();self.thread.join(timeout=.2)
    def remaining_ms(self):
        with self.lock:end=min(self.deadline,self.phase_deadline)
        return max(1,int((end-time.monotonic())*1000))
    def watch(self):
        while not self.stop.wait(.05):
            with self.lock:name=self.name;end=min(self.deadline,self.phase_deadline)
            if time.monotonic()<end:continue
            emit('phase',phase=name,status='TIMEOUT',elapsed_seconds=round(time.monotonic()-self.started,3))
            self.resource_evidence(name,'TIMEOUT');self.stderr();emit('processes',**process_snapshot())
            self.terminate(124);return
    def resource_evidence(self,name,status):
        evidence=task_resources()
        emit('task_resources',phase=name,status=status,evidence=evidence,
             event_deltas={key:event_delta(self.resource_baseline,evidence,key)
                           for key in ('pids.events','pids.events.local','memory.events')})
        if status=='BEGIN':self.resource_baseline=evidence
    @contextlib.contextmanager
    def phase(self,name,seconds=5):
        begin=time.monotonic()
        with self.lock:self.name=name;self.phase_deadline=min(self.deadline,begin+seconds)
        emit('phase',phase=name,status='BEGIN',remaining_ms=self.remaining_ms())
        if name in ('browser_launch','sandbox_page_creation','synthetic_page_creation'):self.resource_evidence(name,'BEGIN')
        try:yield
        except BaseException as exc:
            emit('phase',phase=name,status='FAIL',exception_type=type(exc).__name__,exception=sanitize(exc,512))
            self.resource_evidence(name,'FAIL')
            emit('processes',**process_snapshot());raise
        else:
            if name in ('browser_launch','sandbox_page_creation','synthetic_page_creation'):self.resource_evidence(name,'PASS')
            emit('phase',phase=name,status='PASS',elapsed_seconds=round(time.monotonic()-begin,3))
        finally:
            with self.lock:self.name='between_phases';self.phase_deadline=self.deadline
    def call(self,name,fn,seconds=5):
        with self.phase(name,seconds):return fn()


def snapshot():
    """Read-only allowlist. A profile/filter being present does not prove causality."""
    def read(path):
        try:return sanitize(Path(path).read_text()[:4096],1024).strip()
        except OSError as exc:return 'NOT VERIFIED: '+type(exc).__name__
    # Read only allowlisted status fields.
    try:status=Path('/proc/self/status').read_text()
    except OSError:status=''
    fields={key:re.search(r'^'+key+r':\s*(.*)$',status,re.M).group(1)
            for key in ('Uid','Gid','NoNewPrivs','CapEff','CapBnd','Seccomp','Seccomp_filters')
            if re.search(r'^'+key+r':\s*(.*)$',status,re.M)}
    paths={}
    for path in ('/tmp','/dev/shm','/ms-playwright','/ms-playwright/chromium-1248/chrome-linux64/chrome',
                 '/ms-playwright/chromium-1248/chrome-linux64/chrome_sandbox',
                 '/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell','/opt/google/chrome/chrome'):
        try:
            st=Path(path).stat();paths[path]=dict(mode=oct(st.st_mode&0o7777),uid=st.st_uid,gid=st.st_gid,
                                               executable=os.access(path,os.X_OK),writable=os.access(path,os.W_OK))
        except OSError as exc:paths[path]={'status':'NOT VERIFIED','error':type(exc).__name__}
    readings={path:read(path) for path in (
        '/proc/self/attr/current','/proc/sys/user/max_user_namespaces',
        '/proc/sys/kernel/unprivileged_userns_clone','/proc/sys/kernel/apparmor_restrict_unprivileged_userns',
        '/sys/fs/cgroup/pids.max','/sys/fs/cgroup/pids.current','/sys/fs/cgroup/pids.events',
        '/sys/fs/cgroup/memory.max','/sys/fs/cgroup/memory.events','/sys/fs/cgroup/cpu.max')}
    namespaces={}
    for name in ('user','pid','net'):
        try:namespaces[name]=os.readlink('/proc/self/ns/'+name)
        except OSError:namespaces[name]='NOT VERIFIED'
    space={}
    for path in ('/tmp','/dev/shm'):
        try:
            info=os.statvfs(path);space[path]=info.f_bavail*info.f_frsize
        except OSError:space[path]='NOT VERIFIED'
    emit('sandbox_context',namespaces=namespaces,available_bytes=space,uid=os.getuid(),gid=os.getgid(),status=fields,paths=paths,readings=readings,
         interpretation='Observed configuration only; no kernel policy cause inferred')


def main():
    started=time.monotonic()
    if not Path('/.dockerenv').is_file() or os.getuid()!=10001 or os.getgid()!=10001:
        raise RuntimeError('Real non-root worker container required')
    status=Path('/proc/self/status').read_text()
    if not re.search(r'NoNewPrivs:\s+1',status) or not re.search(r'CapEff:\s+0+\s',status):
        raise RuntimeError('No-new-privileges and zero effective capabilities required')
    memory=Path('/sys/fs/cgroup/memory.max').read_text().strip()
    if memory=='max' or int(memory)>1536*1024*1024:
        raise RuntimeError('Original bounded worker memory policy required')
    from deployment.c3c.build_verify import verify
    verify()
    from playwright.sync_api import sync_playwright
    from browser_isolation import launch_browser,secure_context
    snapshot()
    from validation.c3c.namespace_diagnostics import run_checks
    run_checks()
    with driver_diagnostics() as stderr, ProbeDeadline(started,stderr) as progress:
        # Explicit entry/exit phases distinguish driver connection from browser launch.
        manager=sync_playwright()
        playwright=progress.call('playwright_connection',manager.__enter__)
        try:
            playwright=ObservedPlaywright(playwright,progress)
            browser=progress.call('browser_launch',lambda:launch_browser(playwright),10)
            try:
                version=progress.call('browser_version',lambda:browser.version)
                if version!='156.0.8078.4': raise RuntimeError('Unexpected Chromium version')
                context=progress.call('sandbox_context',browser.new_context)
                try:
                    page=progress.call('sandbox_page_creation',context.new_page)
                    progress.call('sandbox_navigation',lambda:page.goto('chrome://sandbox',timeout=progress.remaining_ms()))
                    text=progress.call('sandbox_text',lambda:page.locator('body').inner_text(timeout=progress.remaining_ms()))
                    with progress.phase('sandbox_verification'):
                        if 'You are adequately sandboxed' not in text or not re.search(r'Seccomp-BPF sandbox\s+Yes',text):
                            raise RuntimeError('Chromium did not positively report the required sandbox')
                    emit('sandbox_page',status='PASS',evidence='Positive Chromium sandbox page and Seccomp-BPF sandbox Yes')
                finally: progress.call('sandbox_context_close',context.close,2)
                context=progress.call('secure_context',lambda:secure_context(browser,user_agent='C3C synthetic acceptance',viewport={'width':800,'height':600}))
                try:
                    page=progress.call('synthetic_page_creation',context.new_page)
                    progress.call('synthetic_content',lambda:page.set_content('<h1>Fixture</h1><a href="/next">Next</a><script>document.body.dataset.js="yes"</script>',timeout=progress.remaining_ms()))
                    with progress.phase('dom_extraction'):
                        if page.locator('h1').inner_text(timeout=progress.remaining_ms())!='Fixture' or page.locator('body').get_attribute('data-js',timeout=progress.remaining_ms())!='yes':
                            raise RuntimeError('Original secure context integration failed')
                    emit('synthetic_dom',status='PASS',scope='Local synthetic JavaScript rendering in original secure context; no external network claim')
                finally: progress.call('secure_context_close',context.close,2)
            finally: progress.call('browser_close',browser.close,2)
        finally: progress.call('playwright_close',lambda:manager.__exit__(None,None,None),2)
        print(json.dumps(dict(status='PASS',uid=os.getuid(),browser_version=version,
                    sandbox='positive chrome://sandbox evidence',synthetic_secure_context=True,
                    scope='No broker/network/mTLS or whole-host containment certification')))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        emit('probe',status='FAIL',exception_type=type(exc).__name__,exception=sanitize(exc))
        sys.exit(1)
