"""Synthetic native acceptance probe. Run only in the capped worker container."""
import json
import os
from pathlib import Path
import re
import sys
import contextlib
import select
import threading


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
    def __init__(self, target): self.target=target
    def __getattr__(self, name): return getattr(self.target, name)
    def launch(self, **kwargs):
        attempt='system_chrome' if kwargs.get('channel')=='chrome' else 'pinned_chromium'
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
    def __init__(self, target):
        self.target=target; self.chromium=ObservedChromium(target.chromium)
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
        yield
    finally:
        os.dup2(saved,2);os.close(saved)
        if write_fd is not None:os.close(write_fd)
        if previous is None:os.environ.pop('DEBUG',None)
        else:os.environ['DEBUG']=previous
        stop.set();thread.join(timeout=2)
        emit('driver_stderr', text=''.join(retained), truncated=truncated,
             capture_complete=not thread.is_alive(), limit_characters=8192)


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
    with driver_diagnostics(), sync_playwright() as playwright:
        playwright=ObservedPlaywright(playwright)
        browser=launch_browser(playwright)
        try:
            if browser.version!='156.0.8078.4': raise RuntimeError('Unexpected Chromium version')
            context=browser.new_context()
            try:
                page=context.new_page();page.goto('chrome://sandbox',timeout=10000)
                text=page.locator('body').inner_text()
                if 'You are adequately sandboxed' not in text or not re.search(r'Seccomp-BPF sandbox\s+Yes',text):
                    raise RuntimeError('Chromium did not positively report the required sandbox')
                emit('sandbox_page',status='PASS',evidence='Positive Chromium sandbox page and Seccomp-BPF sandbox Yes')
            finally: context.close()
            context=secure_context(browser,user_agent='C3C synthetic acceptance',viewport={'width':800,'height':600})
            try:
                page=context.new_page();page.set_content('<h1>Fixture</h1><a href="/next">Next</a><script>document.body.dataset.js="yes"</script>')
                if page.locator('h1').inner_text()!='Fixture' or page.locator('body').get_attribute('data-js')!='yes':
                    raise RuntimeError('Original secure context integration failed')
            finally: context.close()
            print(json.dumps(dict(status='PASS',uid=os.getuid(),browser_version=browser.version,
                  sandbox='positive chrome://sandbox evidence',synthetic_secure_context=True,
                  scope='No broker/network/mTLS or whole-host containment certification')))
        finally: browser.close()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        emit('probe',status='FAIL',exception_type=type(exc).__name__,exception=sanitize(exc))
        sys.exit(1)
