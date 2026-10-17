"""Synthetic native acceptance probe. Run only in the capped worker container."""
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,'/app')


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
    with sync_playwright() as playwright:
        browser=launch_browser(playwright)
        try:
            if browser.version!='156.0.8078.4': raise RuntimeError('Unexpected Chromium version')
            context=browser.new_context()
            try:
                page=context.new_page();page.goto('chrome://sandbox',timeout=10000)
                text=page.locator('body').inner_text()
                if 'You are adequately sandboxed' not in text or not re.search(r'Seccomp-BPF sandbox\s+Yes',text):
                    raise RuntimeError('Chromium did not positively report the required sandbox')
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


if __name__=='__main__':main()
