"""Focused regression checks; mocked Docker/registry behavior is not native acceptance."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from validation.c3c import image_candidate as image
from validation.c3c import run
from deployment.c3c.supervisor import options
from deployment.c3c.policy import Limits


class LoggingTests(unittest.TestCase):
    def test_worker_keeps_bounded_local_logging(self):
        args=options('fixture','a'*32,'sha256:'+'b'*64,Limits())
        self.assertIn('compress=false',args);self.assertIn('max-size=10m',args);self.assertIn('max-file=1',args)
    def test_broker_keeps_bounded_local_logging(self):
        args=options('fixture','a'*32,'sha256:'+'b'*64,Limits(),True)
        self.assertIn('compress=false',args);self.assertIn('max-size=10m',args);self.assertIn('max-file=1',args)
    def test_fixture_keeps_original_log_size(self):
        text=(ROOT/'deployment/c3c/native_runner.py').read_text()
        self.assertIn("'max-size=1m'",text);self.assertIn("'max-file=1'",text);self.assertIn("'compress=false'",text)
    def test_exactly_logging_only_engineering_corrections(self):
        originals=json.loads(run.MANIFEST.read_text())['source_sha256']
        corrections=json.loads((ROOT/'validation/c3c/compatibility-corrections.json').read_text())
        self.assertEqual(set(corrections),{'deployment/c3c/native_runner.py','deployment/c3c/supervisor.py'})
        for name,record in corrections.items():
            raw=(ROOT/name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),record['after'])
            self.assertEqual(hashlib.sha256(raw.replace(b",'--log-opt','compress=false'",b'')).hexdigest(),originals[name])
    def test_worker_security_limits_retained(self):
        args=options('fixture','a'*32,'sha256:'+'b'*64,Limits())
        for flag,value in [('--memory','1536m'),('--memory-swap','1536m'),('--pids-limit','64'),('--cpus','1.0'),('--network','none'),('--user','10001:10001')]:
            self.assertEqual(args[args.index(flag)+1],value)
    def test_stderr_is_bounded_sanitized_and_preserves_failure(self):
        def fail(*a,**kw):
            kw['stderr'].write(b'compression cannot be enabled when max file count is 1 password=hidden '+b'x'*5000)
            return subprocess.CompletedProcess(a[0],1,stdout=b'')
        out=io.StringIO()
        with patch.object(run.subprocess,'run',side_effect=fail),contextlib.redirect_stdout(out):
            with self.assertRaises(RuntimeError):run.diagnostic_runtime()(15).call(['start','synthetic'])
        record=json.loads(out.getvalue().split('DOCKER_DIAGNOSTIC ')[1])
        self.assertEqual(record['exit_code'],1);self.assertTrue(record['stderr_truncated'])
        self.assertLessEqual(len(record['stderr']),4096);self.assertNotIn('hidden',record['stderr'])
        self.assertIn('compression cannot',record['stderr'])


class ImageTests(unittest.TestCase):
    def setUp(self):self.inputs=json.loads(image.INPUTS.read_text())
    def test_exact_runtime_pins(self):image.validate_inputs(self.inputs)
    def test_no_sdk_downgrade(self):
        self.inputs['playwright']='1.63.0'
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_no_python_downgrade(self):
        self.inputs['python']='3.11'
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_no_chromium_downgrade(self):
        self.inputs['chromium_version']='155.0.0.0'
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_browser_manifest_pinned(self):
        self.inputs['bundled_manifest_sha256']='0'*64
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_no_mutable_seed(self):
        self.inputs['seed_image']='mcr.microsoft.com/playwright/python:v1.63.0-noble'
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_no_mutable_donor(self):
        self.inputs['browser_image']='mcr.microsoft.com/playwright:latest'
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_old_browser_revision_rejected(self):
        self.inputs['browser_directories'][0]='chromium-1234'
        with self.assertRaises(image.Blocked):image.validate_inputs(self.inputs)
    def test_registry_digest_mismatch(self):
        class Response(io.BytesIO):headers={}
        with patch.object(image.urllib.request,'urlopen',return_value=Response(b'{}')):
            with self.assertRaises(image.Blocked):image.registry_json('https://example.test','sha256:'+'0'*64)
    def test_registry_missing_stops_without_docker(self):
        with patch.object(image,'verify_remote_images',side_effect=OSError('HTTP 404')),patch.object(run.subprocess,'run') as docker:
            with self.assertRaises(run.ImageUnavailable):run.image_preflight()
            docker.assert_not_called()
    def test_wrong_platform_rejected(self):
        responses=[dict(layers=[{}],config={'digest':'sha256:'+'a'*64}),dict(os='linux',architecture='arm64')]
        with patch.object(image,'registry_json',side_effect=responses):
            with self.assertRaises(image.Blocked):image.verify_remote_images(self.inputs)
    def test_both_images_verified(self):
        responses=[dict(layers=[{}],config={'digest':'sha256:'+'a'*64}),dict(os='linux',architecture='amd64')]*2
        with patch.object(image,'registry_json',side_effect=responses) as registry:
            self.assertEqual(len(image.verify_remote_images(self.inputs)),2);self.assertEqual(registry.call_count,4)
    def test_incomplete_wheel_closure_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(image.Blocked):image.verify_wheels(tmp,self.inputs)
    def test_old_seed_browsers_removed_before_donor_copy(self):
        recipe=image.dockerfile((ROOT/'deployment/c3c/Dockerfile.integrated').read_text())
        self.assertLess(recipe.index('RUN rm -rf /ms-playwright'),recipe.index('COPY --from=browser_donor'))
        for name in self.inputs['browser_directories']:self.assertIn('/ms-playwright/'+name,recipe)
        self.assertEqual(recipe.count('COPY --from=browser_donor'),3)
    def test_recipe_retains_offline_dependency_and_worker_overlay(self):
        recipe=image.dockerfile((ROOT/'deployment/c3c/Dockerfile.integrated').read_text())
        for text in ('--no-index','--require-hashes','USER 10001:10001','build_verify','cp /app/safe_http.py /app/c1_transport.py','verify_candidate_image.py'):self.assertIn(text,recipe)
        for text in ('apt-get','pip install playwright==1.63','--no-sandbox','seccomp=unconfined'):self.assertNotIn(text,recipe)
    def test_unexpected_recipe_fails_closed(self):
        with self.assertRaises(image.Blocked):image.dockerfile('FROM scratch')
    def test_unlisted_source_cannot_be_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir();(source/'private.env').write_text('synthetic')
            with patch.object(image,'verify_wheels',return_value=41):
                with self.assertRaises(image.Blocked):image.prepare(source,Path(tmp)/'wheels',Path(tmp)/'output')
            self.assertFalse((Path(tmp)/'output').exists())
    def test_verified_context_prepares_exact_candidate_recipe(self):
        import shutil
        manifest=json.loads(run.MANIFEST.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir();wheels=Path(tmp)/'wheels';wheels.mkdir()
            for name in manifest['source_sha256']:
                if name.startswith(('.git','.agents','tests/','demo-client-pack/')) or name.endswith(('.key','.pem','.log')):continue
                dest=source/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
            shutil.copyfile(ROOT/'.dockerignore.c3c',source/'.dockerignore')
            with patch.object(image,'verify_wheels',return_value=41):
                result=image.prepare(source,wheels,Path(tmp)/'output')
            self.assertEqual(result['status'],'PREPARED_NOT_NATIVE_VERIFIED')
            output=Path(tmp)/'output'
            self.assertEqual((output/'Dockerfile.candidate').read_text(),image.dockerfile((ROOT/'deployment/c3c/Dockerfile.integrated').read_text()))
            self.assertTrue((output/'validation/c3c/sandbox_probe.py').is_file())
    def test_native_probe_keeps_security_controls(self):
        args=run.browser_options('sha256:'+'a'*64,'b'*32)
        for flag in ('--read-only','--cap-drop','--security-opt'):self.assertIn(flag,args)
        for value in ('no-new-privileges=true','1536m','64','256m','none','10001:10001','compress=false'):self.assertIn(value,' '.join(args))
        self.assertNotIn('--privileged',args);self.assertNotIn('--no-sandbox',args)
    def test_sandbox_probe_never_has_insecure_fallback(self):
        text=(ROOT/'validation/c3c/sandbox_probe.py').read_text()
        self.assertIn('launch_browser(playwright)',text)
        self.assertIn('You are adequately sandboxed',text)
        self.assertNotIn('chromium_sandbox=False',text);self.assertNotIn('--no-sandbox',text)
    def test_native_ipc_fixture_retains_caps_and_readonly_worker_mount(self):
        for broker in (False,True):
            args=run.ipc_options('sha256:'+'a'*64,'b'*32,broker)
            self.assertEqual(args[args.index('--network')+1],'none')
            self.assertEqual(args[args.index('--memory')+1],'256m' if broker else '1536m')
            self.assertEqual(args[args.index('--pids-limit')+1],'16' if broker else '64')
            self.assertIn('compress=false',args);self.assertIn('--read-only',args)
            self.assertEqual(args[args.index('--mount')+1].endswith(',readonly'),not broker)
            self.assertNotIn('--privileged',args)
    def test_native_ipc_fixture_is_denial_only_synthetic(self):
        compile(run.IPC_PROBE,'synthetic-ipc-probe','exec')
        self.assertIn('http://127.0.0.1/',run.IPC_PROBE)
        self.assertIn("get('ok') is False",run.IPC_PROBE)
        self.assertIn('worker_socket_bridge_fails_closed',run.IPC_PROBE)
        self.assertNotIn('verify=False',run.IPC_PROBE)


if __name__=='__main__':unittest.main()
