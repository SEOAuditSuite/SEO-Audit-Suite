"""Controller-to-agent deterministic tests; mocked runtime is not native evidence."""
import base64
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

if sys.platform!='linux':raise unittest.SkipTest('C3C runtime integration targets Linux')
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from deployment.c3c import authentication,controller,agent,client,job,prepare_build
from deployment.c3c.store import Store,Busy,Missing
from test_regressions import fixture_page,discovery

IMAGE='sha256:'+'a'*64


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'queue.sqlite')
        self.keys={'alice':b'a'*32,'bob':b'b'*32};self.api=controller.API(self.store,self.keys)
        self.now=int(time.time());self.serial=0
    def tearDown(self):self.tmp.cleanup()
    def request(self,method,path,body=b'',owner='alice',headers=None,now=None):
        self.serial+=1
        auth=headers if headers is not None else client.headers(self.keys[owner],owner,method,path,body,self.now,format(self.serial,'032x'))
        return self.api.dispatch(method,path,auth,body,self.now if now is None else now)
    def submit(self,owner='alice',nonce=None):
        env=client.envelope(self.keys[owner],owner,'https://example.test/',now=self.now,nonce=nonce)
        code,_,raw=self.request('POST','/v1/jobs',json.dumps(env).encode(),owner)
        return code,json.loads(raw),env
    def test_valid_signed_admission(self):
        code,result,_=self.submit();self.assertEqual(code,202);self.assertEqual(result['status'],'queued')
    def test_missing_authentication_rejected(self):self.assertEqual(self.request('GET','/v1/jobs/'+'a'*32,headers={})[0],401)
    def test_owner_key_cannot_impersonate_other_owner(self):
        headers=client.headers(self.keys['alice'],'bob','GET','/v1/jobs/'+'a'*32,b'',self.now,'b'*32)
        self.assertEqual(self.request('GET','/v1/jobs/'+'a'*32,headers=headers)[0],401)
    def test_request_signature_binds_body(self):
        headers=client.headers(self.keys['alice'],'alice','POST','/v1/jobs',b'old',self.now,'c'*32)
        self.assertEqual(self.request('POST','/v1/jobs',b'new',headers=headers)[0],401)
    def test_request_signature_binds_path(self):
        headers=client.headers(self.keys['alice'],'alice','GET','/v1/jobs/'+'a'*32,b'',self.now,'c'*32)
        self.assertEqual(self.request('GET','/v1/jobs/'+'b'*32,headers=headers)[0],401)
    def test_request_signature_binds_method(self):
        path='/v1/jobs/'+'a'*32;headers=client.headers(self.keys['alice'],'alice','GET',path,b'',self.now,'c'*32)
        self.assertEqual(self.request('DELETE',path,headers=headers)[0],401)
    def test_request_replay_rejected(self):
        path='/v1/jobs/'+'a'*32;headers=client.headers(self.keys['alice'],'alice','GET',path,b'',self.now,'c'*32)
        self.assertEqual(self.request('GET',path,headers=headers)[0],404)
        self.assertEqual(self.request('GET',path,headers=headers)[0],401)
    def test_expired_request_rejected(self):
        self.assertEqual(self.request('GET','/v1/jobs/'+'a'*32,now=self.now+61)[0],401)
    def test_future_request_rejected(self):
        self.assertEqual(self.request('GET','/v1/jobs/'+'a'*32,now=self.now-11)[0],401)
    def test_job_replay_with_new_request_nonce_rejected(self):
        _,_,env=self.submit();self.assertEqual(self.request('POST','/v1/jobs',json.dumps(env).encode())[0],400)
    def test_job_signature_rejected_even_with_valid_request_signature(self):
        env=client.envelope(self.keys['alice'],'alice','https://example.test/',now=self.now);env['job']['pages']=9
        self.assertEqual(self.request('POST','/v1/jobs',json.dumps(env).encode())[0],400)
    def test_oversized_input_rejected_before_auth(self):self.assertEqual(self.request('POST','/v1/jobs',b'x'*16385,headers={})[0],413)
    def test_queue_capacity_is_two(self):
        self.assertEqual(self.submit()[0],202);self.assertEqual(self.submit()[0],202);self.assertEqual(self.submit()[0],429)
    def test_claim_is_single_operation(self):
        self.submit();self.submit();self.assertIsNotNone(self.store.claim());self.assertIsNone(self.store.claim())
    def test_cross_owner_status_hidden(self):
        _,r,_=self.submit();self.assertEqual(self.request('GET','/v1/jobs/'+r['id'],owner='bob')[0],404)
    def test_cross_owner_cancel_hidden(self):
        _,r,_=self.submit();self.assertEqual(self.request('DELETE','/v1/jobs/'+r['id'],owner='bob')[0],404)
        self.assertEqual(self.store.read(r['id'],'alice')['status'],'queued')
    def test_queued_cancel_does_not_launch(self):
        _,r,_=self.submit();code,_,_=self.request('DELETE','/v1/jobs/'+r['id'])
        self.assertEqual(code,202);self.assertIsNone(self.store.claim());self.assertEqual(self.store.read(r['id'],'alice')['status'],'cancelled')
    def test_running_cancel_remains_pending_until_cleanup(self):
        _,r,_=self.submit();self.store.claim();self.request('DELETE','/v1/jobs/'+r['id'])
        self.assertEqual(self.store.read(r['id'],'alice')['status'],'cancelling')
        self.store.finish(r['id'],dict(status='incomplete',cleanup_confirmed=True,files={}))
        self.assertEqual(self.store.read(r['id'],'alice')['status'],'cancelled')
    def completed(self,cleanup=True):
        _,r,_=self.submit();self.store.claim()
        self.store.finish(r['id'],dict(status='completed',cleanup_confirmed=cleanup,
            files={'client-report.html':base64.b64encode(b'<html>report</html>').decode()}))
        return r['id']
    def test_artifact_download_is_attachment_and_sandboxed(self):
        ident=self.completed();code,headers,body=self.request('GET','/v1/jobs/'+ident+'/artifacts/client-report.html')
        self.assertEqual(code,200);self.assertEqual(body,b'<html>report</html>')
        self.assertIn('attachment',headers['Content-Disposition']);self.assertIn('sandbox',headers['Content-Security-Policy'])
    def test_cross_owner_artifact_hidden(self):
        ident=self.completed();self.assertEqual(self.request('GET','/v1/jobs/'+ident+'/artifacts/client-report.html',owner='bob')[0],404)
    def test_artifact_traversal_not_a_route(self):
        ident=self.completed();self.assertEqual(self.request('GET','/v1/jobs/'+ident+'/artifacts/../owners.json')[0],404)
    def test_unknown_artifact_not_exposed(self):
        ident=self.completed();self.assertEqual(self.request('GET','/v1/jobs/'+ident+'/artifacts/secret.json')[0],404)
    def test_status_response_does_not_leak_body_or_target_url(self):
        ident=self.completed();code,_,body=self.request('GET','/v1/jobs/'+ident)
        self.assertEqual(code,200);self.assertNotIn(b'<html>',body);self.assertNotIn(b'example.test',body)
    def test_cleanup_uncertainty_blocks_artifacts_and_new_admission(self):
        ident=self.completed(False)
        self.assertEqual(self.store.read(ident,'alice')['status'],'NOT VERIFIED')
        self.assertEqual(self.request('GET','/v1/jobs/'+ident+'/artifacts/client-report.html')[0],404)
        self.assertEqual(self.submit()[0],429)
    def test_restart_quarantines_interrupted_operation(self):
        self.submit();self.store.claim();Store(self.store.path).reconcile_startup();self.assertEqual(self.submit()[0],429)
    def test_request_rate_limit(self):
        for _ in range(60):self.assertEqual(self.request('GET','/v1/jobs/'+'a'*32)[0],404)
        self.assertEqual(self.request('GET','/v1/jobs/'+'a'*32)[0],429)
    def test_nan_job_expiry_rejected(self):
        env=client.envelope(self.keys['alice'],'alice','https://example.test/',now=self.now);env['job']['expires']=float('nan')
        # Invalid canonical signed input must never enter the queue.
        self.assertEqual(self.request('POST','/v1/jobs',json.dumps(env).encode())[0],400)
    def test_get_with_body_rejected(self):
        ident=self.completed();self.assertEqual(self.request('GET','/v1/jobs/'+ident,b'body')[0],404)
    def test_sqlite_storage_error_is_not_an_seo_failure(self):
        with patch.object(self.store,'consume_request',side_effect=__import__('sqlite3').OperationalError('full')):
            code,_,body=self.request('POST','/v1/jobs',b'{}')
        self.assertEqual(code,503);self.assertIn(b'no audit result inferred',body)


class AgentTests(unittest.TestCase):
    # Shared fixture helpers, without repeating the controller test cases.
    setUp=ControllerTests.setUp
    tearDown=ControllerTests.tearDown
    request=ControllerTests.request
    submit=ControllerTests.submit
    def make_agent(self,executor):
        return agent.Agent(self.store,self.keys,self.tmp.name,IMAGE,IMAGE,executor)
    def test_agent_revalidates_before_execution(self):
        self.submit();executor=Mock(return_value=dict(status='completed',cleanup_confirmed=True,files={}))
        self.assertTrue(self.make_agent(executor).tick(self.now));self.assertEqual(executor.call_count,1)
    def test_expired_queued_job_does_not_execute(self):
        _,r,_=self.submit();executor=Mock();self.make_agent(executor).tick(self.now+301)
        executor.assert_not_called();self.assertEqual(self.store.read(r['id'],'alice')['status'],'incomplete')
    def test_cancelled_runtime_interrupts_active_loop(self):
        _,r,_=self.submit()
        def executor(job,*args,runtime,**kwargs):
            self.store.cancel(job['nonce'],job['owner'])
            with self.assertRaises(agent.Cancelled):_ = runtime.deadline
            return dict(status='incomplete',cleanup_confirmed=True,files={})
        self.make_agent(executor).tick(self.now)
        self.assertEqual(self.store.read(r['id'],'alice')['status'],'cancelled')
    def test_cancel_does_not_prevent_cleanup_commands(self):
        runtime=agent.CancellableRuntime(10,lambda:True)
        with self.assertRaises(agent.Cancelled):runtime.call(['info'])
        with patch('deployment.c3c.supervisor.subprocess.run',return_value=Mock(stdout=b'',returncode=0)) as run:
            runtime.call(['rm','--force','owned'],cleanup=True)
        run.assert_called_once()
    def test_cancel_state_failure_fails_closed(self):
        def unavailable():raise RuntimeError('database inaccessible')
        with self.assertRaises(agent.Cancelled):_ = agent.CancellableRuntime(10,unavailable).deadline
    def test_broker_failure_is_incomplete_without_fake_status(self):
        _,r,_=self.submit()
        executor=Mock(return_value=dict(status='incomplete',cleanup_confirmed=True,http_status=None,files={},reason='broker unavailable'))
        self.make_agent(executor).tick(self.now)
        value=json.loads(self.store.read(r['id'],'alice')['result'])
        self.assertIsNone(value['http_status']);self.assertEqual(value['files'],{})
    def test_unexpected_executor_escape_quarantines_admission(self):
        _,r,_=self.submit();self.make_agent(Mock(side_effect=RuntimeError('escape'))).tick(self.now)
        self.assertEqual(self.store.read(r['id'],'alice')['status'],'NOT VERIFIED');self.assertEqual(self.submit()[0],429)
    def test_reconcile_refuses_surviving_container(self):
        with self.assertRaises(RuntimeError):agent.reconcile(self.store,self.tmp.name,Mock(call=Mock(return_value=b'owned')))
    def test_reconcile_requires_no_owned_volumes(self):
        runtime=Mock();runtime.call.side_effect=[b'',b'owned-ipc']
        with self.assertRaises(RuntimeError):agent.reconcile(self.store,self.tmp.name,runtime)


class KeyAndBuildTests(unittest.TestCase):
    def test_group_writable_key_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'keys.json';p.write_text(json.dumps({'alice':'a'*64}));p.chmod(0o660)
            with self.assertRaises(authentication.Denied):authentication.load_keys(p)
    def test_independent_keys_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'keys.json';p.write_text(json.dumps({'alice':'a'*64,'bob':'a'*64}));p.chmod(0o600)
            with self.assertRaises(authentication.Denied):authentication.load_keys(p)
    def test_private_key_file_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'keys.json';p.write_text(json.dumps({'alice':'a'*64}));p.chmod(0o640)
            self.assertEqual(len(authentication.load_keys(p)['alice']),32)
    def test_build_manifest_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir();(source/'app.py').write_text('changed')
            m=Path(tmp)/'manifest.json';m.write_text(json.dumps(dict(source_sha256={'app.py':'0'*64})))
            with self.assertRaises(ValueError):prepare_build.prepare(source,m,Path(tmp)/'context')
    def test_unlisted_secret_never_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir();(source/'app.py').write_bytes(b'print(1)')
            (source/'.dockerignore.c3c').write_bytes(b'.env\n');(source/'.env').write_text('secret')
            records={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('app.py','.dockerignore.c3c')}
            m=Path(tmp)/'manifest.json';m.write_text(json.dumps(dict(source_sha256=records)))
            context=prepare_build.prepare(source,m,Path(tmp)/'context')
            self.assertFalse((context/'.env').exists());self.assertTrue((context/'app.py').exists())
    def test_wheel_digest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'wheels').mkdir();(p/'wheels/a.whl').write_bytes(b'wrong')
            (p/'lock').write_text('test==1 --hash=sha256:'+'0'*64+'\n')
            with self.assertRaises(ValueError):prepare_build.verify_wheels(p/'wheels',p/'lock')


class PipelineCompatibilityTests(unittest.TestCase):
    def run_job(self):
        raw=json.dumps(dict(url='https://example.test/',pages=5)).encode()
        stdin=io.TextIOWrapper(io.BytesIO(raw));stdout=io.StringIO()
        with patch.object(sys,'stdin',stdin),patch.object(sys,'stdout',stdout):job.main()
        return json.loads(stdout.getvalue())
    def test_real_pipeline_preserves_scores_and_all_nine_export_bytes(self):
        import client_workflow as cw
        from reportlab import rl_config
        crawl=dict(pages=[fixture_page()],errors=[],browser_used=False,
                   coverage=dict(observed_graph_complete=True,full_site_complete=False,pages_inspected=1,
                                 requested_limit=5,remaining_queue=[],stop_reason='queue_exhausted',
                                 attempted_urls=1,discovered_urls=1,skipped_discoveries=0))
        fixed=datetime(2026,10,16,12,0,tzinfo=timezone.utc)
        clock=Mock();clock.now.return_value=fixed
        with patch.object(cw,'crawl_site',return_value=crawl),patch.object(cw,'get_robots_sitemap',return_value=discovery()),patch.object(cw,'datetime',clock),patch.object(rl_config,'invariant',1):
            baseline=cw.build_delivery('https://example.test/',crawl_limit=5)
            expected=cw.delivery_files(baseline)
            result=self.run_job()
        self.assertEqual(result['status'],'completed');actual={k:base64.b64decode(v) for k,v in result['files'].items()}
        self.assertEqual(len(actual),9);self.assertEqual(actual,expected)
        self.assertEqual(json.loads(actual['evidence.json'])['audit'],json.loads(json.dumps(baseline['evidence']['audit'])))
    def test_no_pages_returns_unknown_not_seo_failure(self):
        with patch('client_workflow.crawl_site',return_value=dict(pages=[],errors=[])):value=self.run_job()
        self.assertEqual(value['status'],'incomplete');self.assertIsNone(value['http_status']);self.assertEqual(value['files'],{})


class NativeControllerTests(unittest.TestCase):
    def test_real_unix_server_construction_when_permitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            try:server=controller.Server(str(Path(tmp)/'api.sock'),controller.Handler)
            except PermissionError as exc:self.skipTest('NOT VERIFIED: Unix socket creation denied: '+str(exc))
            else:server.server_close()


if __name__=='__main__':unittest.main()
