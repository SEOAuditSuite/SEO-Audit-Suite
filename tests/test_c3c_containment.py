"""C3C control flow and real Unix IPC tests, NOT native container acceptance."""
import base64
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

if sys.platform!='linux':
    raise unittest.SkipTest('C3C harness targets Linux; Windows C3B acceptance remains separate')

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deployment.c3c.policy import Limits,authorize,canonical,owned_result
from deployment.c3c import broker,supervisor,reaper,native_runner
import safe_http

# Import the image-only overlay without replacing production safe_http.
spec=importlib.util.spec_from_file_location('c3c_remote',ROOT/'deployment/c3c/remote_transport.py')
remote=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{'c1_transport':safe_http}):spec.loader.exec_module(remote)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.key=b'k'*32
        self.job=dict(owner='client1',nonce='a'*32,expires=200,url='https://example.org/',pages=5)
    def envelope(self):
        return dict(job=self.job,signature=hmac.new(self.key,canonical(self.job),hashlib.sha256).hexdigest())
    def test_signed_owner_admitted(self):self.assertEqual(authorize(self.envelope(),self.key,'client1',100),self.job)
    def test_wrong_owner_rejected(self):
        with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client2',100)
    def test_tampering_rejected(self):
        env=self.envelope();env['job']['pages']=10
        with self.assertRaises(ValueError):authorize(env,self.key,'client1',100)
    def test_expired_rejected(self):
        with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client1',200)
    def test_long_expiry_rejected(self):
        with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client1',-101)
    def test_weak_key_rejected(self):
        with self.assertRaises(ValueError):authorize(self.envelope(),b'a','client1',100)
    def test_credential_urls_rejected(self):
        self.job['url']='https://user:password@example.org/'
        with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client1',100)
    def test_unsupported_port_rejected(self):
        self.job['url']='https://example.org:22/'
        with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client1',100)
    def test_page_limit_and_bool_rejected(self):
        for pages in (0,11,True):
            self.job['pages']=pages
            with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client1',100)
    def test_nonce_path_rejected(self):
        self.job['nonce']='../some-file'
        with self.assertRaises(ValueError):authorize(self.envelope(),self.key,'client1',100)
    def test_limits_reject_unbounded_or_nonfinite(self):
        for values in (dict(pids=0),dict(memory_mib=0),dict(cpu=float('nan')),dict(seconds=True),dict(output_bytes=999999999)):
            with self.assertRaises(ValueError):Limits(**values)
    def test_result_cross_owner_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'a'*32+'-result.json').write_text(json.dumps(dict(owner='client1',files={})))
            self.assertEqual(owned_result(tmp,'a'*32,'client1')['files'],{})
            with self.assertRaises(ValueError):owned_result(tmp,'a'*32,'client2')
    def test_result_traversal_rejected(self):
        with self.assertRaises(ValueError):owned_result('/tmp','../secret','client1')


class ContainerPolicyTests(unittest.TestCase):
    def args(self,broker=False):return supervisor.options('c3c-test','a'*32,'sha256:'+'b'*64,Limits(),broker)
    def test_worker_network_none(self):
        args=self.args();self.assertEqual(args[args.index('--network')+1],'none')
    def test_broker_network_separate(self):
        args=self.args(True);self.assertEqual(args[args.index('--network')+1],'seo-c3c-broker')
    def test_no_host_mount_or_secret_env(self):
        args=self.args();text=' '.join(args)
        self.assertNotIn('type=bind',text);self.assertNotIn('docker.sock',text);self.assertNotIn('API_KEY',text)
        self.assertNotIn('--privileged',args)
    def test_cpu_memory_pid_storage_explicit(self):
        args=self.args()
        for name in ('--memory','--memory-swap','--cpus','--pids-limit','--tmpfs'):self.assertIn(name,args)
        self.assertEqual(args[args.index('--memory')+1],args[args.index('--memory-swap')+1])
    def test_nonroot_readonly_caps_and_expiry(self):
        args=self.args();text=' '.join(args)
        for name in ('10001:10001','--read-only','ALL','no-new-privileges=true','seo.c3c.expires='):self.assertIn(name,text)
    def test_mutable_image_rejected(self):
        for value in ('latest','image:tag','sha256:short'):
            with self.assertRaises(ValueError):supervisor.image_id(value)
    def test_readback_mismatch_fails(self):
        with self.assertRaises(RuntimeError):supervisor.verify_container(dict(Config={},HostConfig={}),Limits())
    def test_runtime_failure_still_attempts_cleanup(self):
        class BrokenRuntime:
            calls=[]
            def call(self,args,**kwargs):
                self.calls.append(args)
                if args[0]=='ps':return b''
                raise RuntimeError('unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp,0o700);run=BrokenRuntime()
            value=supervisor.execute(dict(nonce='a'*32),'sha256:'+'b'*64,'sha256:'+'c'*64,tmp,runtime=run)
            self.assertEqual(value['status'],'incomplete');self.assertIsNone(value['http_status'])
            self.assertTrue(any(c[0]=='ps' for c in run.calls))
    def test_nonce_replay_rejected(self):
        class Runtime:
            def call(self,args,**kwargs):
                if args[0]=='ps':return b''
                raise RuntimeError('unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp,0o700);job=dict(nonce='a'*32)
            supervisor.execute(job,'sha256:'+'b'*64,'sha256:'+'c'*64,tmp,runtime=Runtime())
            with self.assertRaises(FileExistsError):supervisor.execute(job,'sha256:'+'b'*64,'sha256:'+'c'*64,tmp,runtime=Runtime())
    def test_cleanup_failure_never_completed(self):
        class Runtime:
            def call(self,*args,**kwargs):raise RuntimeError('unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp,0o700)
            value=supervisor.execute(dict(nonce='a'*32),'sha256:'+'b'*64,'sha256:'+'c'*64,tmp,runtime=Runtime())
            self.assertEqual(value['status'],'NOT VERIFIED');self.assertFalse(value['cleanup_confirmed'])
            self.assertTrue(Path(tmp,'ADMISSION-BLOCKED').is_file())
            with self.assertRaisesRegex(RuntimeError,'Admission blocked'):
                supervisor.execute(dict(nonce='b'*32),'sha256:'+'b'*64,'sha256:'+'c'*64,tmp,runtime=Runtime())


class IPCTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'broker.sock')
        try:self.server=broker.Broker(self.path,broker.Handler)
        except PermissionError as exc:
            self.tmp.cleanup()
            self.skipTest('NOT VERIFIED: environment denies Unix sockets: '+str(exc))
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs=dict(poll_interval=.01));self.thread.start()
        self.patch=patch.object(remote,'SOCKET',self.path);self.patch.start()
    def tearDown(self):
        self.patch.stop();self.server.shutdown();self.server.server_close();self.thread.join(2);self.tmp.cleanup()
    def test_real_c1_private_address_denied_over_ipc(self):
        with self.assertRaises(safe_http.TransportError):remote.SafeSession().get('http://127.0.0.1/')
    def test_no_redirect_following_or_credentials(self):
        with self.assertRaises(safe_http.TransportError):remote.SafeSession().get('https://example.org/',allow_redirects=True)
        with self.assertRaises(safe_http.TransportError):remote.SafeSession().get('https://user:password@example.org/')
    def test_missing_socket_fails_closed(self):
        with patch.object(remote,'SOCKET',self.path+'-missing'):
            with self.assertRaises(safe_http.TransportError):remote.SafeSession().get('https://example.org/')
    def test_byte_budget_consumed_on_failure(self):
        session=remote.SafeSession(max_total_bytes=32)
        with self.assertRaises(safe_http.TransportError):session.get('http://127.0.0.1/')
        self.assertEqual(session.decoded_bytes,32)
        with self.assertRaises(safe_http.TransportError):session.get('https://example.org/')
    def test_broker_preserves_redirect_status_and_location(self):
        response=safe_http.Response();response.status_code=302;response.url='https://example.org/'
        response.headers={'Location':'https://cdn.example.org/next?x=1'};response._content=b''
        with patch.object(self.server.session,'get',return_value=response) as get:
            value=remote.SafeSession().get(response.url)
        self.assertEqual(value.status_code,302);self.assertEqual(value.headers['Location'],response.headers['Location'])
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
    def test_body_and_query_preserved(self):
        response=safe_http.Response();response.status_code=200;response.url='https://example.org/a?x=%2F&x=2'
        response.headers={'Content-Type':'text/html'};response._content=b'<h1>Rendered fixture</h1>'
        with patch.object(self.server.session,'get',return_value=response):value=remote.SafeSession().get(response.url)
        self.assertEqual(value.content,response.content);self.assertEqual(value.url,response.url)
    def test_expired_broker_and_request_count_deny(self):
        self.server.requests=500
        with self.assertRaises(safe_http.TransportError):remote.SafeSession().get('https://example.org/')
    def test_non_get_schema_rejected(self):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
            conn.connect(self.path);conn.sendall(b'{"method":"CONNECT"}\n')
            reply=json.loads(conn.recv(1024))
        self.assertFalse(reply['ok'])
    def test_tiny_deadline_and_nonfinite_rejected(self):
        for deadline in (time.monotonic()-1,float('nan')):
            with self.assertRaises(safe_http.TransportError):remote.SafeSession().get('https://example.org/',deadline=deadline)
    def test_remote_helper_keeps_c1_error_identity(self):self.assertIs(remote.TransportError,safe_http.TransportError)


class ReaperTests(unittest.TestCase):
    def test_ownership_mismatch_never_removed(self):
        class Runtime:
            calls=[]
            def call(self,args,**kwargs):
                self.calls.append(args)
                if args[0]=='ps':return b'abcdef123456'
                return json.dumps([dict(Name='/unrelated',Config=dict(Labels={}))]).encode()
        runtime=Runtime()
        with self.assertRaises(RuntimeError):reaper.reap(runtime,100)
        self.assertFalse(any(c[0]=='rm' for c in runtime.calls))
    def test_expired_job_only_cleanup(self):
        class Runtime:
            calls=[];listed=0
            def call(self,args,**kwargs):
                self.calls.append(args)
                if args[0]=='ps':
                    self.listed+=1
                    return b'abcdef123456' if self.listed==1 else b''
                if args[0]=='inspect':return json.dumps([dict(Name='/c3c-'+'a'*32+'-worker',Config=dict(Labels={supervisor.LABEL:'a'*32,'seo.c3c.expires':'90'}))]).encode()
                return b''
        runtime=Runtime();self.assertEqual(reaper.reap(runtime,100),['a'*32])
        self.assertIn(['rm','--force','abcdef123456'],runtime.calls)


class BrokerProtocolTests(unittest.TestCase):
    """Deterministic protocol tests using buffers, not native IPC evidence."""
    def invoke(self,request,*,session=None,requests=0,deadline=None):
        from types import SimpleNamespace
        from unittest.mock import Mock
        handler=object.__new__(broker.Handler)
        handler.connection=Mock();handler.rfile=io.BytesIO(request);handler.wfile=io.BytesIO()
        handler.server=SimpleNamespace(session=session or Mock(),requests=requests,
            deadline=time.monotonic()+30 if deadline is None else deadline)
        handler.handle()
        return json.loads(handler.wfile.getvalue()),handler.server
    def request(self,**changes):
        value=dict(url='https://example.org/',headers={},max_bytes=128,seconds=5);value.update(changes)
        return json.dumps(value).encode()+b'\n'
    def test_malformed_json_unknown(self):self.assertFalse(self.invoke(b'{\n')[0]['ok'])
    def test_missing_delimiter_rejected(self):self.assertFalse(self.invoke(b'{}')[0]['ok'])
    def test_oversized_request_rejected(self):self.assertFalse(self.invoke(b'x'*16385+b'\n')[0]['ok'])
    def test_post_method_rejected(self):self.assertFalse(self.invoke(self.request(method='POST'))[0]['ok'])
    def test_file_scheme_rejected(self):self.assertFalse(self.invoke(self.request(url='file:///etc/passwd'))[0]['ok'])
    def test_nonweb_port_rejected(self):self.assertFalse(self.invoke(self.request(url='https://example.org:22/'))[0]['ok'])
    def test_userinfo_rejected(self):self.assertFalse(self.invoke(self.request(url='https://a:b@example.org/'))[0]['ok'])
    def test_nan_timeout_rejected(self):self.assertFalse(self.invoke(self.request(seconds=float('nan')))[0]['ok'])
    def test_negative_body_rejected(self):self.assertFalse(self.invoke(self.request(max_bytes=-1))[0]['ok'])
    def test_boolean_budget_rejected(self):self.assertFalse(self.invoke(self.request(max_bytes=True))[0]['ok'])
    def test_exhausted_count_rejected(self):self.assertFalse(self.invoke(self.request(),requests=500)[0]['ok'])
    def test_expired_budget_rejected(self):self.assertFalse(self.invoke(self.request(),deadline=0)[0]['ok'])
    def test_no_query_in_error(self):
        value=self.invoke(self.request(url='file:///etc/password?secret=token'))[0]
        self.assertNotIn('token',json.dumps(value));self.assertNotIn('password',json.dumps(value))
    def test_c1_called_without_automatic_redirects(self):
        from unittest.mock import Mock
        response=safe_http.Response();response.url='https://example.org/';response.status_code=302
        response.headers={'Location':'https://cdn.example.org/next?x=%2F'};response._content=b''
        session=Mock();session.get.return_value=response
        value,_=self.invoke(self.request(),session=session)
        self.assertTrue(value['ok']);self.assertEqual(value['status'],302)
        self.assertEqual(value['headers']['Location'],response.headers['Location'])
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])


class NativeJudgementTests(unittest.TestCase):
    """Parser tests only; never presented as Windows/Linux enforcement proof."""
    def test_oom_exit_without_native_flag_is_not_pass(self):
        logs=json.dumps(dict(stage='started'))+'\n'
        self.assertFalse(native_runner.judge('memory',dict(ExitCode=137,OOMKilled=False),logs))
        self.assertTrue(native_runner.judge('memory',dict(ExitCode=137,OOMKilled=True),logs))
    def test_pid_exception_without_counter_not_pass(self):
        logs='\n'.join(map(json.dumps,[dict(stage='started'),dict(stage='pid_creation_refused',events='max 0')]))
        self.assertFalse(native_runner.judge('processes',dict(ExitCode=0),logs))
    def test_cpu_requires_throttling_and_bounded_rate(self):
        row=dict(stage='cpu_measurement',wall=2,cpu=.2,before='nr_throttled 0\nthrottled_usec 0',after='nr_throttled 3\nthrottled_usec 1000000')
        logs='\n'.join(map(json.dumps,[dict(stage='started'),row]))
        self.assertTrue(native_runner.judge('cpu',dict(ExitCode=0),logs))
        row['after']=row['before'];logs='\n'.join(map(json.dumps,[dict(stage='started'),row]))
        self.assertFalse(native_runner.judge('cpu',dict(ExitCode=0),logs))


if __name__=='__main__':unittest.main()
