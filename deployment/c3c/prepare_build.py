"""Create a clean build context from an exact review manifest, never a broad copy."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def prepare(source,manifest,output):
    source=Path(source).resolve();output=Path(output)
    records=json.loads(Path(manifest).read_text())['source_sha256']
    if output.exists():raise ValueError('Refusing existing build context')
    verified=[]
    for name,digest in records.items():
        path=source/name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Unsafe source manifest path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Source checksum mismatch: '+name)
        verified.append((name,path))
    output.mkdir(mode=0o700,parents=True)
    for name,path in verified:
        if name.startswith(('.git','.agents','tests/','demo-client-pack/')) or name.endswith(('.key','.pem','.log')):
            continue
        dest=output/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    # No broad source COPY is performed until the exact context has been verified.
    shutil.copy2(source/'.dockerignore.c3c',output/'.dockerignore')
    (output/'wheelhouse').mkdir()
    return output


def verify_wheels(directory,lock):
    expected={}
    for line in Path(lock).read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r'([a-z0-9-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})',line)
        if not match:raise ValueError('Invalid pinned dependency line')
        expected[match[3]]=match[1]
    actual={hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(directory).iterdir() if p.is_file()}
    if actual!=set(expected):raise ValueError('Downloaded wheel hashes do not exactly match the lock')
    return len(actual)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for flag in ('source','manifest','output'):parser.add_argument('--'+flag,required=True,type=Path)
    parser.add_argument('--download-wheels',action='store_true');args=parser.parse_args()
    context=prepare(args.source,args.manifest,args.output)
    if args.download_wheels:
        subprocess.run([sys.executable,'-m','pip','--isolated','download','--no-deps',
            '--only-binary=:all:','--require-hashes','--index-url','https://pypi.org/simple',
            '--dest',str(context/'wheelhouse'),'-r',str(context/'deployment/c3c/requirements.linux.lock')],check=True,timeout=300)
        print('Verified wheel count:',verify_wheels(context/'wheelhouse',context/'deployment/c3c/requirements.linux.lock'))
    print(context)
