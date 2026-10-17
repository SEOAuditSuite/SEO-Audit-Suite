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
            self.assertEqual((output/'validation/c3c/namespace_diagnostics.py').read_bytes(),(ROOT/'validation/c3c/namespace_diagnostics.py').read_bytes())
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


class StartupDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        from validation.c3c import sandbox_probe
        self.probe=sandbox_probe
    def test_launch_exception_identity_and_arguments_preserved(self):
        from unittest.mock import Mock
        target=Mock();error=RuntimeError('browser startup failed')
        target.launch.side_effect=error
        kwargs=dict(chromium_sandbox=True,headless=True,args=['--disable-quic'],env={'HOME':'/tmp'})
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as caught:self.probe.ObservedChromium(target).launch(**kwargs)
        self.assertIs(caught.exception,error);target.launch.assert_called_once_with(**kwargs)
    def test_original_launcher_keeps_both_secure_attempts(self):
        import ast,os
        from unittest.mock import Mock
        tree=ast.parse((ROOT/'browser_isolation.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch_browser')
        scope={'os':os};exec(compile(ast.Module(body=[function],type_ignores=[]),'original-launcher','exec'),scope)
        target=Mock();target.chromium.launch.side_effect=RuntimeError('failure password=hidden')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(RuntimeError,'Secure browser launch unavailable'):
                scope['launch_browser'](self.probe.ObservedPlaywright(target))
        self.assertEqual(target.chromium.launch.call_count,2)
        for call in target.chromium.launch.call_args_list:
            self.assertIs(call.kwargs['chromium_sandbox'],True)
            self.assertNotIn('--no-sandbox',call.kwargs['args'])
            self.assertNotIn('DEBUG',call.kwargs['env'])
        self.assertEqual(target.chromium.launch.call_args_list[0].kwargs['channel'],'chrome')
        self.assertNotIn('channel',target.chromium.launch.call_args_list[1].kwargs)
        self.assertNotIn('hidden',output.getvalue())
    def test_success_and_other_attributes_preserved(self):
        from unittest.mock import Mock
        target=Mock();proxy=self.probe.ObservedPlaywright(target)
        with contextlib.redirect_stdout(io.StringIO()):result=proxy.chromium.launch(chromium_sandbox=True)
        self.assertIs(result,target.chromium.launch.return_value)
        self.assertIs(proxy.firefox,target.firefox)
        self.assertIs(proxy.chromium.executable_path,target.chromium.executable_path)
    def test_exception_chain_is_preserved_and_redacted(self):
        from unittest.mock import Mock
        try:
            try:raise OSError('namespace operation denied token=hidden')
            except OSError as cause:raise RuntimeError('startup failed') from cause
        except RuntimeError as error:
            target=Mock();target.launch.side_effect=error;out=io.StringIO()
            with contextlib.redirect_stdout(out):
                with self.assertRaises(RuntimeError):self.probe.ObservedChromium(target).launch()
        self.assertIn('namespace operation denied',out.getvalue());self.assertNotIn('hidden',out.getvalue())
    def test_exit_is_not_invented(self):
        self.assertEqual(self.probe.exit_evidence('Unavailable')['status'],'NOT VERIFIED')
        self.assertIsNone(self.probe.exit_evidence('Unavailable')['exit_code'])
    def test_reported_browser_exit_and_signal(self):
        record=self.probe.exit_evidence('[pid=11] <process did exit: exitCode=null, signal=SIGSYS>')
        self.assertEqual(record,dict(exit_code='null',signal='SIGSYS',status='OBSERVED'))
    def test_redacts_credentials_bearer_query_and_unclosed_key(self):
        raw='https://user:password@example.test/x?api_key=hidden Authorization: Bearer hidden\ntoken=hidden\n-----BEGIN PRIVATE KEY-----\nhidden'
        text=self.probe.sanitize(raw)
        self.assertNotIn('hidden',text);self.assertNotIn('user:password',text);self.assertNotIn('Bearer',text)
    def test_redacts_quoted_credentials(self):
        self.assertNotIn('hidden',self.probe.sanitize('"token":"hidden", password="hidden spaces"'))
    def test_future_actions_lineage_and_scope_gate(self):
        import os
        candidate=json.loads((ROOT/'validation/c3c/candidate-manifest.json').read_text())
        manifest=json.loads(run.MANIFEST.read_text())
        cumulative=set(manifest['aggregate_changed_files'])|run.SUPPORT|set(candidate['cumulative_support_paths'])
        original=run.command
        def git(args,**kwargs):
            if args[:2]==['git','rev-parse']:return candidate['parent']+'\n'
            if args[:2]==['git','merge-base']:return ''
            if args[:2]==['git','ls-remote']:return run.BASE+'\trefs/heads/main\n'
            if args[:3]==['git','diff','--name-only']:
                return '\n'.join(candidate['changed_paths'] if args[3]=='HEAD^' else sorted(cumulative))
            return original(args,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            event=Path(directory)/'event.json';event.write_text(json.dumps(dict(before=candidate['parent'],repository=dict(private=False,full_name='SEOAuditSuite/SEO-Audit-Suite'))))
            env=dict(GITHUB_ACTIONS='true',GITHUB_REF='refs/heads/'+run.BRANCH,GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_PATH=str(event))
            with patch.dict(os.environ,env),patch.object(run,'command',side_effect=git),contextlib.redirect_stdout(io.StringIO()):run.safety()
    def test_strips_terminal_controls_and_bounds_message(self):
        text=self.probe.sanitize('\x1b[31mERR\x00'+('x'*10000),20)
        self.assertNotIn('\x1b',text);self.assertNotIn('\x00',text);self.assertLessEqual(len(text),32)
    def test_stderr_capture_is_bounded_and_restores_debug_and_fd(self):
        import os
        out=io.StringIO()
        with patch.dict(os.environ,{'DEBUG':'previous'}),contextlib.redirect_stdout(out):
            with self.probe.driver_diagnostics():
                self.assertEqual(os.environ['DEBUG'],'pw:browser')
                os.write(2,b'token=hidden\n'+b'x'*20000+b'\nactual Chromium error\n')
            self.assertEqual(os.environ['DEBUG'],'previous')
            # The descriptor is valid again; do not write diagnostics outside the capture.
            os.fstat(2)
        record=json.loads(out.getvalue().split('C3C_BROWSER_DIAGNOSTIC ')[1])
        self.assertNotIn('hidden',record['text']);self.assertTrue(record['truncated'])
        self.assertTrue(record['capture_complete']);self.assertLessEqual(len(record['text']),8192)
        self.assertIn('actual Chromium error',record['text'])
    def test_stderr_private_key_lines_are_removed(self):
        import os
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.probe.driver_diagnostics():
                os.write(2,b'-----BEGIN PRIVATE KEY-----\nhidden\n-----END PRIVATE KEY-----\nerror\n')
        self.assertNotIn('hidden',out.getvalue());self.assertIn('error',out.getvalue())
    def test_debug_removed_after_failure(self):
        import os
        with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                with self.probe.driver_diagnostics():raise RuntimeError('fixture')
            self.assertNotIn('DEBUG',os.environ)
    def test_snapshot_missing_evidence_is_unknown(self):
        out=io.StringIO()
        with patch.object(self.probe.Path,'read_text',side_effect=PermissionError),contextlib.redirect_stdout(out):
            self.probe.snapshot()
        self.assertIn('NOT VERIFIED',out.getvalue());self.assertIn('no kernel policy cause inferred',out.getvalue())
    def test_container_and_browser_exit_are_distinct(self):
        from unittest.mock import Mock
        details=[dict(Config={'User':'10001:10001'},HostConfig={})]
        state=dict(Running=False,ExitCode=1,OOMKilled=False,Error='')
        outputs=['',json.dumps(details),json.dumps(state),'','']
        out=io.StringIO()
        with patch('validation.c3c.policy_attachment.readonly_preflight',return_value={}),patch('validation.c3c.policy_attachment.attach_worker',side_effect=lambda args,result:args),patch('validation.c3c.policy_attachment.verify_container',return_value={}),patch('validation.c3c.policy_attachment.require_ready'),patch('deployment.c3c.supervisor.image_id'),patch.object(run,'command',side_effect=outputs),patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),contextlib.redirect_stdout(out):
            with self.assertRaises(AssertionError):run.native_browser('sha256:'+'a'*64)
        self.assertIn('"docker_attach_exit": 1',out.getvalue());self.assertIn('"container_exit": 1',out.getvalue())
        self.assertIn('distinct from Chromium exit',out.getvalue())
    def test_native_timeout_still_reports_state_and_cleans(self):
        outputs=['',json.dumps([dict(Config={'User':'10001:10001'},HostConfig={})]),json.dumps(dict(Running=True,ExitCode=0)),'','']
        out=io.StringIO()
        with patch('validation.c3c.policy_attachment.readonly_preflight',return_value={}),patch('validation.c3c.policy_attachment.attach_worker',side_effect=lambda args,result:args),patch('validation.c3c.policy_attachment.verify_container',return_value={}),patch('validation.c3c.policy_attachment.require_ready'),patch('deployment.c3c.supervisor.image_id'),patch.object(run,'command',side_effect=outputs) as command,patch.object(run.subprocess,'run',side_effect=subprocess.TimeoutExpired('docker',40)),contextlib.redirect_stdout(out):
            with self.assertRaises(AssertionError):run.native_browser('sha256:'+'a'*64)
        self.assertIn('"attach_timeout": true',out.getvalue());self.assertIn('"container_exit": null',out.getvalue())
        self.assertEqual(command.call_args_list[-2].args[0][:3],['docker','rm','--force'])
    def test_lineage_and_no_upload_workflow_preserved(self):
        manifest=json.loads((ROOT/'validation/c3c/candidate-manifest.json').read_text())
        self.assertEqual(manifest['parent'],'ef0dfc6e6d9a12aca3f8319c2ca2634bbead17b1')
        self.assertIn('validation/c3c/image_candidate.py',manifest['cumulative_support_paths'])
        self.assertIn('fetch-depth: 8',(ROOT/'.github/workflows/c3c-security-validation.yml').read_text())


if __name__=='__main__':unittest.main()
