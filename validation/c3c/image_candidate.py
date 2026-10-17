"""Prepare an offline image from two immutable official inputs; never execute Docker."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[2]
INPUTS=Path(__file__).with_name('image-inputs.json')


class Blocked(ValueError):pass


def sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def validate_inputs(inputs):
    original=json.loads((ROOT/'deployment/c3c/build-inputs.json').read_text())
    revisions=json.loads((ROOT/'deployment/c3c/browser-revisions.json').read_text())
    for field in ('python','architecture','playwright'):
        if inputs[field]!=original[field]:raise Blocked('Runtime requirement mismatch: '+field)
    if inputs['bundled_manifest_sha256']!=revisions['bundled_manifest_sha256']:
        raise Blocked('Bundled browser manifest mismatch')
    if inputs['chromium_version']!=revisions['browsers'][0]['browserVersion']:
        raise Blocked('Chromium version mismatch')
    if inputs['browser_directories']!=['chromium-1248','chromium_headless_shell-1248','ffmpeg-1013']:
        raise Blocked('Unexpected browser revisions')
    for field,repository in [('seed_image','playwright/python'),('browser_image','playwright')]:
        if not re.fullmatch(r'mcr\.microsoft\.com/'+repository+r'@sha256:[a-f0-9]{64}',inputs[field]):
            raise Blocked('Immutable official image required: '+field)


def registry_json(url,digest):
    req=urllib.request.Request(url,headers={'Accept':'application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'})
    with urllib.request.urlopen(req,timeout=20) as response:
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise Blocked('Registry response exceeds cap')
        actual='sha256:'+hashlib.sha256(raw).hexdigest()
        if actual!=digest:raise Blocked('Registry content digest mismatch')
        if response.headers.get('Docker-Content-Digest',actual)!=actual:
            raise Blocked('Registry digest header mismatch')
    return json.loads(raw)


def verify_remote_images(inputs):
    validate_inputs(inputs);rows=[]
    for field in ('seed_image','browser_image'):
        reference=inputs[field];repository,digest=reference.split('@')
        endpoint='https://mcr.microsoft.com/v2/'+repository.split('/',1)[1]
        manifest=registry_json(endpoint+'/manifests/'+digest,digest)
        if not manifest.get('layers') or not manifest.get('config',{}).get('digest'):
            raise Blocked('Platform image manifest required')
        config=registry_json(endpoint+'/blobs/'+manifest['config']['digest'],manifest['config']['digest'])
        if config.get('os')!='linux' or config.get('architecture')!='amd64':
            raise Blocked('Image platform mismatch')
        rows.append(dict(role=field,image=reference,platform='linux/amd64',layers=len(manifest['layers'])))
    return rows


def verify_wheels(directory,inputs):
    expected={}
    for line in (ROOT/'deployment/c3c/requirements.linux.lock').read_text().splitlines():
        if not line or line.startswith('#'):continue
        match=re.fullmatch(r'([^ =]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})',line)
        if not match:raise Blocked('Malformed dependency lock')
        expected[match[3]]=(match[1],match[2])
    files=list(Path(directory).iterdir())
    if any(p.is_symlink() or not p.is_file() or p.suffix!='.whl' for p in files):raise Blocked('Only regular wheels allowed')
    actual={sha(p):p for p in files}
    if len(files)!=41 or len(actual)!=41 or set(actual)!=set(expected):raise Blocked('Exact 41-wheel closure required')
    wheel=actual.get(inputs['wheel_sha256'])
    if not wheel or expected[inputs['wheel_sha256']]!=('playwright','1.64.0'):raise Blocked('Pinned Playwright wheel required')
    with zipfile.ZipFile(wheel) as archive:raw=archive.read('playwright/driver/package/browsers.json')
    if hashlib.sha256(raw).hexdigest()!=inputs['bundled_manifest_sha256']:raise Blocked('Actual SDK browser manifest mismatch')
    return len(actual)


def dockerfile(original):
    prefix='ARG BASE_IMAGE\nFROM ${BASE_IMAGE} AS common'
    anchor='RUN python -m deployment.c3c.build_verify '+chr(92)+'\n'
    if original.count(prefix)!=1 or original.count(anchor)!=1:raise Blocked('Unexpected engineering Dockerfile structure')
    recipe=original.replace(prefix,'ARG BASE_IMAGE\nARG BROWSER_IMAGE\nFROM ${BROWSER_IMAGE} AS browser_donor\nFROM ${BASE_IMAGE} AS common',1)
    copies='RUN rm -rf /ms-playwright\n'+''.join('COPY --from=browser_donor /ms-playwright/'+name+' /ms-playwright/'+name+'\n'
            for name in ['chromium-1248','chromium_headless_shell-1248','ffmpeg-1013'])
    copies+='RUN chmod -R a+rX,go-w /ms-playwright\nENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright\n'
    recipe=recipe.replace(anchor,copies+anchor,1)
    # Verify actual executable versions and dynamic libraries after the original SDK check.
    recipe=recipe.replace('FROM common AS broker','RUN python /app/validation/c3c/verify_candidate_image.py\n\nFROM common AS broker',1)
    return recipe


def prepare(source_context,wheels,output):
    inputs=json.loads(INPUTS.read_text());validate_inputs(inputs);verify_wheels(wheels,inputs)
    source=Path(source_context);output=Path(output)
    if output.exists():raise Blocked('Refuse existing context')
    original=json.loads((ROOT/'validation/c3c/source-manifest.json').read_text())
    corrections=json.loads((ROOT/'validation/c3c/compatibility-corrections.json').read_text())
    expected={n:d for n,d in original['source_sha256'].items() if not n.startswith(('.git','.agents','tests/','demo-client-pack/')) and not n.endswith(('.key','.pem','.log'))}
    for name,record in corrections.items():
        if original['source_sha256'][name]!=record['before']:raise Blocked('Correction lineage mismatch')
        expected[name]=record['after']
    expected['.dockerignore']=original['source_sha256']['.dockerignore.c3c']
    actual={p.relative_to(source).as_posix():sha(p) for p in source.rglob('*') if p.is_file()}
    if source.is_symlink() or any(p.is_symlink() for p in source.rglob('*')) or actual!=expected:raise Blocked('Sanitized context mismatch')
    recipe=dockerfile((source/'deployment/c3c/Dockerfile.integrated').read_text())
    shutil.copytree(source,output)
    if (output/'wheelhouse').exists():shutil.rmtree(output/'wheelhouse')
    shutil.copytree(wheels,output/'wheelhouse')
    for name in ('sandbox_probe.py','verify_candidate_image.py','namespace_diagnostics.py'):
        target=output/'validation/c3c'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(__file__).with_name(name),target)
    (output/'Dockerfile.candidate').write_text(recipe)
    (output/'candidate-image-inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    return dict(status='PREPARED_NOT_NATIVE_VERIFIED',context=str(output),seed_image=inputs['seed_image'],browser_image=inputs['browser_image'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('source-context','wheelhouse','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    try:print(json.dumps(prepare(args.source_context,args.wheelhouse,args.output),indent=2))
    except (Blocked,OSError) as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc))),file=sys.stderr);raise SystemExit(2)
