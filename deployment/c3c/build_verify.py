"""Build-time version/browser-file checks; not a successful sandbox launch."""
import importlib.metadata
import importlib.util
import hashlib
import json
from pathlib import Path
import platform
import sys


def verify():
    root=Path(__file__).resolve().parent
    expected=json.loads((root/'build-inputs.json').read_text())
    if sys.platform!='linux' or sys.version_info[:2]!=(3,12) or platform.machine() not in ('x86_64','AMD64'):
        raise RuntimeError('CPython 3.12 on Linux amd64 required')
    if importlib.metadata.version('playwright')!=expected['playwright']:
        raise RuntimeError('Pinned Playwright version mismatch')
    revisions=json.loads((root/'browser-revisions.json').read_text())
    bundled=Path(importlib.util.find_spec('playwright').origin).parent/'driver/package/browsers.json'
    if hashlib.sha256(bundled.read_bytes()).hexdigest()!=revisions['bundled_manifest_sha256']:
        raise RuntimeError('Pinned Playwright browser revision manifest mismatch')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        path=Path(p.chromium.executable_path)
        if not path.is_file():raise RuntimeError('Matching Chromium executable missing from pinned base')
    print('Versions and Chromium file verified; actual non-root sandbox launch remains a native gate')


if __name__=='__main__':verify()
