"""Actual build-time executable checks. These do not certify a sandbox launch."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys


def main():
    inputs=json.loads(Path('/app/candidate-image-inputs.json').read_text())
    if sys.version_info[:2]!=(3,12) or importlib.metadata.version('playwright')!='1.64.0':
        raise RuntimeError('Runtime version mismatch')
    root=Path('/ms-playwright')
    if sorted(p.name for p in root.iterdir())!=sorted(inputs['browser_directories']):
        raise RuntimeError('Unexpected or retained seed browsers')
    for relative in ('chromium-1248/chrome-linux64/chrome','chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell'):
        path=root/relative
        result=subprocess.run([str(path),'--version'],capture_output=True,text=True,check=True,timeout=10)
        if inputs['chromium_version'] not in result.stdout:raise RuntimeError('Executable browser version mismatch')
        result=subprocess.run(['ldd',str(path)],capture_output=True,text=True,check=True,timeout=10)
        if 'not found' in result.stdout:raise RuntimeError('Required shared libraries missing')
    print('PASS: exact Python/SDK/browser executable versions and dynamic libraries; native sandbox remains separate')


if __name__=='__main__':main()
