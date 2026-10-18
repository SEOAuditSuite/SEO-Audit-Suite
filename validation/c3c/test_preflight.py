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
        for value in ('no-new-privileges=true','1536m','128','256m','none','10001:10001','compress=false'):self.assertIn(value,' '.join(args))
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
        self.assertEqual(manifest['parent'],'a1a73548532b1aa8b001123dee0b0850c880700d')
        self.assertIn('validation/c3c/image_candidate.py',manifest['cumulative_support_paths'])
        self.assertIn('fetch-depth: 10',(ROOT/'.github/workflows/c3c-security-validation.yml').read_text())


class RecoveryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        from validation.c3c import sandbox_probe
        self.probe=sandbox_probe
    def test_every_postlaunch_stage_reports_timeout_stderr_and_processes(self):
        from unittest.mock import Mock
        phases=('playwright_connection','browser_launch','browser_version','sandbox_context','sandbox_page_creation',
                'sandbox_navigation','sandbox_text','sandbox_verification','secure_context',
                'synthetic_page_creation','synthetic_content','dom_extraction','browser_close','playwright_close')
        for phase in phases:
            out=io.StringIO();terminate=Mock();stderr=Mock()
            deadline=self.probe.ProbeDeadline(0,stderr,terminate=terminate)
            deadline.name=phase;deadline.phase_deadline=1;deadline.stop.wait=Mock(return_value=False)
            with patch.object(self.probe.time,'monotonic',return_value=2),patch.object(self.probe,'process_snapshot',return_value={'status':'OBSERVED','processes':[]}),contextlib.redirect_stdout(out):deadline.watch()
            self.assertIn('"phase": "'+phase+'"',out.getvalue());self.assertIn('TIMEOUT',out.getvalue())
            self.assertIn('processes',out.getvalue());self.assertNotIn('"status": "PASS"',out.getvalue())
            stderr.assert_called_once();terminate.assert_called_once_with(124)
    def test_phase_failure_preserves_original_error_and_redacts(self):
        out=io.StringIO();error=RuntimeError('token=hidden')
        progress=self.probe.ProbeDeadline(0,lambda:None)
        with patch.object(self.probe,'process_snapshot',return_value={'status':'NOT VERIFIED'}),contextlib.redirect_stdout(out):
            with self.assertRaises(RuntimeError) as caught:
                progress.call('dom_extraction',lambda:(_ for _ in ()).throw(error))
        self.assertIs(caught.exception,error);self.assertIn('FAIL',out.getvalue());self.assertNotIn('hidden',out.getvalue())
    def test_launch_timeout_uses_remaining_phase_budget(self):
        from unittest.mock import Mock
        target=Mock();progress=Mock();progress.remaining_ms.return_value=1234
        with contextlib.redirect_stdout(io.StringIO()):
            self.probe.ObservedChromium(target,progress).launch(chromium_sandbox=True,timeout=30000)
        self.assertEqual(target.launch.call_args.kwargs,dict(chromium_sandbox=True,timeout=1234))
    def test_global_budget_caps_phase_and_never_resets(self):
        progress=self.probe.ProbeDeadline(10,lambda:None)
        with patch.object(self.probe.time,'monotonic',return_value=43),contextlib.redirect_stdout(io.StringIO()):
            with progress.phase('sandbox_navigation',5):self.assertEqual(progress.remaining_ms(),1000)
        self.assertEqual(progress.deadline,44)
    def test_real_stalled_child_emits_phase_before_hard_exit(self):
        script="""import time
from validation.c3c.sandbox_probe import ProbeDeadline,emit,sanitize
with ProbeDeadline(time.monotonic(),lambda:emit('driver_stderr',text=sanitize('token=hidden')),total=.25) as p:
    with p.phase('synthetic_page_creation',.1):time.sleep(5)
"""
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,124);self.assertIn('TIMEOUT',result.stdout)
        self.assertIn('synthetic_page_creation',result.stdout);self.assertIn('driver_stderr',result.stdout)
        self.assertIn('processes',result.stdout);self.assertNotIn('hidden',result.stdout)
    @unittest.skipUnless(sys.platform=='linux','Actual fd2 pipe/select capture requires Linux')
    def test_real_stall_retains_actual_driver_pipe_stderr(self):
        script="""import os,time
from validation.c3c.sandbox_probe import ProbeDeadline,driver_diagnostics
with driver_diagnostics() as stderr, ProbeDeadline(time.monotonic(),stderr,total=1) as p:
    os.write(2,b'token=hidden\\nrenderer stalled\\n')
    with p.phase('sandbox_page_creation',.3):time.sleep(5)
"""
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,124);self.assertIn('renderer stalled',result.stdout)
        self.assertIn('TIMEOUT',result.stdout);self.assertNotIn('hidden',result.stdout)
    def test_process_snapshot_never_reads_commands_or_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);entry=root/'123';entry.mkdir()
            (entry/'status').write_text('Name:\tchromium\nState:\tS\nPPid:\t1\nThreads:\t2\n')
            (entry/'wchan').write_text('futex_wait')
            (entry/'cmdline').write_text('token=hidden');(entry/'environ').write_text('secret=hidden')
            report=self.probe.process_snapshot(root)
            self.assertEqual(report['processes'][0]['PPid'],'1');self.assertNotIn('hidden',json.dumps(report))
    def test_watchdog_starts_after_single_threaded_negative_checks(self):
        source=Path(self.probe.__file__).read_text()
        self.assertLess(source.index('    run_checks()'),source.index('ProbeDeadline(started,stderr)'))
        self.assertIn('timeout=40',Path(run.__file__).read_text())
    def modeled_probe(self,sandbox=True,close_error=False):
        import os
        from types import SimpleNamespace
        from unittest.mock import Mock
        from validation.c3c import namespace_diagnostics as ns
        browser=Mock();browser.version='156.0.8078.4';context=browser.new_context.return_value
        page=context.new_page.return_value
        body=Mock();body.inner_text.return_value='You are adequately sandboxed Seccomp-BPF sandbox Yes' if sandbox else 'unknown'
        body.get_attribute.return_value='yes';heading=Mock();heading.inner_text.return_value='Fixture'
        page.locator.side_effect=lambda name:heading if name=='h1' else body
        if close_error:browser.close.side_effect=RuntimeError('close failed')
        manager=Mock();playwright=Mock();playwright.chromium.launch.return_value=browser;manager.__enter__=Mock(return_value=playwright);manager.__exit__=Mock(return_value=False)
        modules={'deployment.c3c.build_verify':SimpleNamespace(verify=Mock()),
                 'playwright':SimpleNamespace(),'playwright.sync_api':SimpleNamespace(sync_playwright=lambda:manager),
                 'browser_isolation':SimpleNamespace(launch_browser=lambda p:p.chromium.launch(chromium_sandbox=True),secure_context=lambda *a,**k:context)}
        out=io.StringIO()
        def read(path,*args,**kw):return '1024' if str(path).endswith('memory.max') else 'NoNewPrivs:\t1\nCapEff:\t0000\n'
        with patch.dict(sys.modules,modules),patch.object(os,'getuid',return_value=10001,create=True),patch.object(os,'getgid',return_value=10001,create=True),patch.object(self.probe.Path,'is_file',return_value=True),patch.object(self.probe.Path,'read_text',autospec=True,side_effect=read),patch.object(self.probe,'snapshot'),patch.object(ns,'run_checks'),patch.object(self.probe,'driver_diagnostics',return_value=contextlib.nullcontext(lambda:None)),patch.object(self.probe,'process_snapshot',return_value={'status':'NOT VERIFIED'}),contextlib.redirect_stdout(out):
            try:self.probe.main();error=None
            except RuntimeError as exc:error=exc
        return out.getvalue(),error,browser,page
    def test_complete_modeled_sequence_keeps_positive_gates_and_close_phases(self):
        output,error,browser,page=self.modeled_probe()
        self.assertIsNone(error);self.assertIn('"kind": "sandbox_page", "status": "PASS"',output)
        self.assertIn('dom_extraction',output);self.assertIn('playwright_close',output)
        self.assertEqual(browser.close.call_count,1)
        self.assertEqual(page.goto.call_args.args[0],'chrome://sandbox')
        self.assertLessEqual(page.goto.call_args.kwargs['timeout'],5000)
    def test_negative_sandbox_stops_before_synthetic_dom(self):
        output,error,browser,page=self.modeled_probe(sandbox=False)
        self.assertIsNotNone(error);self.assertIn('sandbox_verification',output)
        self.assertNotIn('synthetic_dom',output);page.set_content.assert_not_called()
        browser.close.assert_called_once()
    def test_close_failure_never_emits_final_probe_success(self):
        output,error,_,_=self.modeled_probe(close_error=True)
        self.assertIsNotNone(error);self.assertIn('"phase": "browser_close", "status": "FAIL"',output)
        self.assertNotIn('"synthetic_secure_context": true',output)


class TaskAttributionTests(unittest.TestCase):
    def setUp(self):
        from validation.c3c import sandbox_probe
        self.probe=sandbox_probe
    def test_numeric_counter_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'counter';p.write_text('max 7\n')
            self.assertEqual(self.probe.numeric_read(p),{'max':'7'})
            p.write_text('64\n');self.assertEqual(self.probe.numeric_read(p),'64')
    def test_missing_counter_never_becomes_zero(self):
        self.assertIn('NOT VERIFIED',self.probe.numeric_read(Path('/missing/c3c/counter')))
    def test_malformed_secret_never_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'counter';p.write_text('token=secret')
            self.assertNotIn('secret',self.probe.numeric_read(p))
    def test_oversized_counter_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'counter';p.write_text('9'*2048)
            self.assertIn('oversized',self.probe.numeric_read(p))
    def delta(self,a,b):
        return self.probe.event_delta({'cgroup':{'pids.events':a}},{'cgroup':{'pids.events':b}},'pids.events')
    def test_denial_delta_preserved(self):self.assertEqual(self.delta({'max':'0'},{'max':'3'}),{'max':3})
    def test_no_denial_observed_is_not_compatibility_pass(self):self.assertEqual(self.delta({'max':'0'},{'max':'0'}),{'max':0})
    def test_missing_denial_evidence_is_unknown(self):self.assertEqual(self.delta(None,{'max':'1'}),'NOT VERIFIED')
    def test_counter_reset_is_unknown(self):self.assertIn('NOT VERIFIED',self.delta({'max':'2'},{'max':'1'}))
    def test_resource_capture_does_not_spawn_or_change_limits(self):
        from unittest.mock import Mock
        with patch.object(self.probe.threading,'Thread',side_effect=AssertionError('thread')),patch.object(self.probe.resource,'setrlimit',side_effect=AssertionError('write')):
            data=self.probe.task_resources(cgroup=Path('/missing'),proc=Path('/missing'))
        self.assertEqual(data['ancestor_limits'],'NOT VERIFIED')
        self.assertEqual(data['host_uid_task_total'],'NOT VERIFIED')
    def test_pre_and_failure_evidence_precedes_unwind(self):
        out=io.StringIO();progress=self.probe.ProbeDeadline(0,lambda:None)
        with patch.object(self.probe,'task_resources',return_value={'cgroup':{'pids.events':{'max':'1'}}}),contextlib.redirect_stdout(out):
            with self.assertRaisesRegex(RuntimeError,'crashed'):
                progress.call('sandbox_page_creation',lambda:(_ for _ in ()).throw(RuntimeError('crashed')))
        events=[json.loads(line.split(' ',1)[1]) for line in out.getvalue().splitlines()]
        self.assertEqual([e['status'] for e in events if e['kind']=='task_resources'],['BEGIN','FAIL'])
    def test_task_count_sums_threads_not_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pid,threads in ((1,3),(19,11)):
                p=Path(tmp)/str(pid);p.mkdir();(p/'status').write_text('Threads:\t'+str(threads)+'\n');(p/'wchan').write_text('0')
            result=self.probe.process_snapshot(Path(tmp))
        self.assertEqual(result['observed_thread_count'],14);self.assertEqual(result['observed_process_count'],2)
    def test_policy_and_explicit_validation_task_cap(self):
        args=run.browser_options('sha256:test','a'*32)
        self.assertEqual(args[args.index('--pids-limit')+1],'128')
        self.assertIn('--cap-drop',args);self.assertIn('ALL',args)


if __name__=='__main__':unittest.main()
