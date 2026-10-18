"""Mocked attachment tests do not establish native enforcement."""
import contextlib
import copy
import io
import hashlib
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
from validation.c3c import policy_attachment as a,run,namespace_diagnostics as ns

IMAGE='sha256:'+'a'*64


def ready():
    names=('package_identity','docker_local_defaults','cgroup_controllers','apparmor_features','namespace_restrictions','named_enforcing_profile_identity','docker_default_profile_identity')
    return dict(status='PASS',checks={n:'PASS' for n in names},evidence=dict(named_enforcing_profile_identity=dict(binary_sha256='b'*64),docker_default_profile_identity='c'*64))


def details():
    return dict(Image=IMAGE,AppArmorProfile=a.policy.PROFILE,Mounts=[],Config=dict(User='10001:10001',Image=IMAGE,Entrypoint=['python'],Cmd=['/app/validation/c3c/sandbox_probe.py']),
        HostConfig=dict(Memory=1536*1024*1024,MemorySwap=1536*1024*1024,NanoCpus=1000000000,PidsLimit=128,
        NetworkMode='none',IpcMode='private',CgroupnsMode='private',UsernsMode='',PidMode='',ReadonlyRootfs=True,Privileged=False,CapAdd=None,CapDrop=['ALL'],
        Tmpfs={'/tmp':'rw,nosuid,nodev,size=256m,mode=1777'},LogConfig={'Type':'local','Config':{'max-size':'10m','max-file':'1','compress':'false'}},
        Ulimits=[dict(Name='nofile',Soft=256,Hard=256),dict(Name='core',Soft=0,Hard=0)],
        SecurityOpt=['no-new-privileges=true','apparmor='+a.policy.PROFILE,'seccomp='+json.dumps(a.policy.build())]))


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        # These fixtures model direct host reads, not a prepared hosted-job receipt.
        # Workflow-level environment must not redirect them into real sudo queries.
        self.enterContext(patch.dict(os.environ,{'C3C_POLICY_JOB':''}))
        self.enterContext(patch.object(a,'privileged_receipt',side_effect=AssertionError('Unexpected privileged receipt query in isolated attachment fixture')))
    def test_preserved_proposal_package_identity(self):self.assertEqual(len(a.verify_package()),2)
    def test_worker_attachment_only_adds_two_policy_options(self):
        args=run.browser_options(IMAGE,'a'*32)
        with patch.object(a,'require_ready'):new=a.attach_worker(args,ready())
        i=new.index('--security-opt',new.index('--security-opt')+1)
        self.assertEqual(new[:i]+new[i+4:],args)
        self.assertIn('apparmor='+a.policy.PROFILE,new)
    def test_broker_controller_and_other_entrypoints_rejected(self):
        for replacement in ('c3c-'+'a'*32+'-broker','controller'):
            args=run.browser_options(IMAGE,'a'*32);args[args.index('--name')+1]=replacement
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.attach_worker(args,ready())
        args=run.browser_options(IMAGE,'a'*32);args[-1]='-m deployment.c3c.controller'
        with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.attach_worker(args,ready())
    def test_unsafe_or_duplicate_create_options_rejected(self):
        for extra in (['--privileged=true'],['--cap-add','SYS_ADMIN'],['--network','host'],['--mount','type=bind,src=/,dst=/host']):
            args=run.browser_options(IMAGE,'a'*32);args[1:1]=extra
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.attach_worker(args,ready())
    def test_changed_bounds_and_mutable_image_rejected(self):
        for flag,value in (('--memory','2g'),('--user','0:0'),('--pids-limit','64'),('--cpus','2.0')):
            args=run.browser_options(IMAGE,'a'*32);args[args.index(flag)+1]=value
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.attach_worker(args,ready())
        args=run.browser_options('image:latest','a'*32)
        with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.attach_worker(args,ready())
    def test_incomplete_preflight_prevents_container_creation(self):
        with patch.object(a,'readonly_preflight',return_value={'status':'NOT VERIFIED'}),patch('deployment.c3c.supervisor.image_id'),patch.object(run,'command') as command:
            with self.assertRaises(a.Blocked):run.native_browser(IMAGE)
        command.assert_not_called()
    def test_exact_docker_inspect_evidence_accepted(self):
        with patch.object(a,'require_ready'):self.assertEqual(a.verify_container(details(),ready())['status'],'PASS')
    def test_path_only_seccomp_or_default_profile_rejected(self):
        for replacement in ('seccomp=/reviewed/file.json','seccomp=unconfined'):
            d=details();d['HostConfig']['SecurityOpt'][-1]=replacement
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(d,ready())
        d=details();d['AppArmorProfile']='docker-default'
        with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(d,ready())
    def test_effective_resource_privilege_network_mutations_rejected(self):
        for key,value in [('Privileged',True),('CapAdd',['SYS_ADMIN']),('NetworkMode','host'),('Memory',2**31),('ReadonlyRootfs',False),('PidsLimit',64),('IpcMode','host'),('Binds',['/:/host'])]:
            d=details();d['HostConfig'][key]=value
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(d,ready())
    def test_effective_image_seccomp_and_mount_mutations_rejected(self):
        d=details();d['Image']='sha256:'+'f'*64
        with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(d,ready())
        d=details();p=a.policy.build();p['defaultAction']='SCMP_ACT_ALLOW';d['HostConfig']['SecurityOpt'][-1]='seccomp='+json.dumps(p)
        with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(d,ready())
        d=details();d['Mounts']=[dict(Type='bind',Destination='/host')]
        with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(d,ready())
    def test_profile_identity_change_and_missing_checks_rejected(self):
        with patch.object(a,'loaded_profile',return_value='f'*64),self.assertRaises(a.Blocked):a.require_ready(ready())
        report=ready();report['checks'].pop('apparmor_features')
        with self.assertRaises(a.Blocked):a.require_ready(report)
    def test_securityfs_name_mode_and_raw_hash_required(self):
        with tempfile.TemporaryDirectory() as folder:
            aa=Path(folder);entry=aa/'policy/profiles/named.1';entry.mkdir(parents=True)
            for name,value in [('name',a.policy.PROFILE),('mode','enforce'),('raw_sha256','b'*64)]: (entry/name).write_text(value)
            self.assertEqual(a.loaded_profile(a.policy.PROFILE,aa),'b'*64)
            (entry/'mode').write_text('complain')
            with self.assertRaises(a.Blocked):a.loaded_profile(a.policy.PROFILE,aa)
    def test_remote_wrong_version_or_disabled_security_rejected(self):
        d=dict(ServerVersion='28.0.4',OSType='linux',CgroupVersion='2',Architecture='x86_64',SecurityOptions=['name=apparmor','name=seccomp,profile=builtin'])
        a.require_docker(d,'unix:///var/run/docker.sock')
        for key,value in [('ServerVersion','29.0'),('CgroupVersion','1'),('SecurityOptions',[]),('Architecture','arm64')]:
            changed=dict(d);changed[key]=value
            with self.assertRaises(a.Blocked):a.require_docker(changed,'unix:///var/run/docker.sock')
        with self.assertRaises(a.Blocked):a.require_docker(d,'tcp://remote')
    def test_host_failure_report_is_bounded_and_no_loading(self):
        with patch.object(a,'command',side_effect=FileNotFoundError('fixture')),patch.object(a,'compile_host_profile') as compile:
            report=a.readonly_preflight()
        self.assertEqual(report['status'],'NOT VERIFIED');self.assertLess(len(json.dumps(report)),10000)
    def test_cleanup_after_policy_verification_failure(self):
        outputs=['',json.dumps([details()]),'','']
        with patch.object(a,'readonly_preflight',return_value=ready()),patch.object(a,'attach_worker',side_effect=lambda args,r:args),patch.object(a,'verify_container',side_effect=a.Blocked('identity mismatch')),patch('deployment.c3c.supervisor.image_id'),patch.object(run,'command',side_effect=outputs) as command:
            with self.assertRaises(a.Blocked):run.native_browser(IMAGE)
        self.assertEqual(command.call_args_list[-2].args[0][:3],['docker','rm','--force'])
    def test_default_policy_change_blocks_preservation_check(self):
        with patch.object(a,'loaded_profile',return_value='d'*64),self.assertRaises(a.Blocked):a.verify_defaults(ready())
    def test_namespace_denial_stops_before_positive_clone(self):
        class Lib:
            syscall=Mock()
            def setns(self,*args):return 0
        with patch.object(ns,'guard'),patch.object(ns.ctypes,'CDLL',return_value=Lib()),patch.object(ns,'clone_probe') as clone,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):ns.run_checks()
        clone.assert_not_called()
    def test_namespace_child_timeout_kills_and_reaps_owned_child(self):
        lib=Mock();lib.syscall.return_value=12345
        with patch.object(ns.time,'monotonic',side_effect=[0,4]),patch.object(ns.os,'kill') as kill,patch.object(ns.os,'waitpid',return_value=(12345,9)) as wait:
            result=ns.clone_probe(lib,ns.NEWUSER|17)
        self.assertEqual(result['error'],'Timeout');kill.assert_called_once_with(12345,ns.signal.SIGKILL);wait.assert_called_once_with(12345,0)
    def test_namespace_mapping_failure_preserves_phase_and_errno(self):
        import errno
        with patch.object(ns.Path,'write_text',side_effect=PermissionError(errno.EPERM,'fixture')):
            result=ns.namespace_child(Mock())
        self.assertEqual(result['stage'],'uid_gid_mapping');self.assertEqual(result['errno'],errno.EPERM)
    def test_valid_read_only_identity_receipt_is_accepted(self):
        with patch.object(a,'loaded_profile',side_effect=['b'*64,'c'*64]):self.assertEqual(a.require_ready(ready()),'b'*64)
    def test_enforcing_name_without_raw_binary_hash_is_insufficient(self):
        with tempfile.TemporaryDirectory() as folder:
            aa=Path(folder);entry=aa/'policy/profiles/named.1';entry.mkdir(parents=True)
            (entry/'name').write_text(a.policy.PROFILE);(entry/'mode').write_text('enforce')
            with self.assertRaises(FileNotFoundError):a.loaded_profile(a.policy.PROFILE,aa)
    def test_native_namespace_guard_is_never_executed_in_offline_suite(self):
        source=Path(ns.__file__).read_text()
        self.assertIn('os.getuid()!=10001',source);self.assertIn('Single-threaded namespace probe required',source)
        self.assertIn('Seccomp filtering required',source)
    def test_native_browser_uses_real_attachment_and_inspection_guards(self):
        import subprocess
        outputs=['',json.dumps([details()]),json.dumps(dict(Running=False,ExitCode=0,OOMKilled=False,Error='')),'','']
        with patch.object(a,'readonly_preflight',return_value=ready()),patch.object(a,'loaded_profile',side_effect=lambda name:'b'*64 if name==a.policy.PROFILE else 'c'*64),patch('deployment.c3c.supervisor.image_id'),patch.object(run,'command',side_effect=outputs) as command,patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(run,'browser_evidence',return_value={'mocked':'not native evidence'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.native_browser(IMAGE)['status'],'PASS')
        create=command.call_args_list[0].args[0]
        self.assertIn('apparmor='+a.policy.PROFILE,create)
        self.assertIn('seccomp='+str(a.policy.ROOT/'chromium-amd64.seccomp.json'),create)
    def test_ipc_worker_and_broker_remain_on_original_boundaries(self):
        for broker in (False,True):
            args=run.ipc_options(IMAGE,'a'*32,broker)
            self.assertFalse(any(arg.startswith(('apparmor=','seccomp=')) for arg in args))
            self.assertIn('no-new-privileges=true',args)
    def test_preflight_code_contains_no_policy_loading_or_host_writes(self):
        import inspect
        source=inspect.getsource(a.readonly_preflight)+inspect.getsource(a.compile_host_profile)
        for token in ("'--add'","'--replace'","'--remove'","'sudo'"):
            self.assertNotIn(token,source)
        self.assertIn("'--skip-kernel-load'",source)


class SameRunnerTests(unittest.TestCase):
    def setUp(self):
        run.OWNED_NONCES.clear();run.OWNED_IMAGES.clear()
    def tearDown(self):
        run.OWNED_NONCES.clear();run.OWNED_IMAGES.clear()
    def state(self,folder,owned=True):
        directory=Path(folder)/'owned';directory.mkdir(mode=0o700)
        binary=b'exact synthetic compile output';(directory/'profile.bin').write_bytes(binary)
        state=dict(job='123-1',profile=a.policy.PROFILE,owned=owned,phase='loaded' if owned else 'reserved',
                   before={'docker-default':dict(mode='enforce',sha256='c'*64)},
                   compiled=dict(binary_sha256=hashlib.sha256(binary).hexdigest(),expanded_sha256='e'*64))
        a.write_state(directory,state);return directory,state
    def test_first_attempt_scope_and_path_traversal(self):
        for job in ('../host','123-2','0-1','1-1/../../x','x','1-1\n'):
            with self.assertRaises(a.Blocked):a.state_directory(job)
        self.assertEqual(str(a.state_directory('123-1')),'/run/c3c-sandbox-123-1')
    def test_collision_never_loads_adopts_or_replaces(self):
        with patch.object(a.os,'geteuid',return_value=0),patch.object(a,'verify_package'),patch.object(a,'trusted_parser',return_value='/trusted/parser'),patch.object(a,'inventory',return_value={a.policy.PROFILE:{}}),patch.object(a,'command') as command:
            with self.assertRaises(a.Blocked):a.prepare_job('123-1')
        command.assert_not_called()
    def test_missing_structure_prevents_load(self):
        before={'docker-default':dict(mode='enforce',sha256='c'*64)}
        with patch.object(a.os,'geteuid',return_value=0),patch.object(a,'verify_package'),patch.object(a,'trusted_parser'),patch.object(a,'inventory',return_value=before),patch.object(a,'readonly_preflight',return_value=dict(checks={'docker_local_defaults':'NOT VERIFIED'})),patch.object(a,'command') as command:
            with self.assertRaises(a.Blocked):a.prepare_job('123-1')
        command.assert_not_called()
    def test_successful_prepare_uses_add_only_exact_private_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)/'owned'
            before={'docker-default':dict(mode='enforce',sha256='c'*64)}
            preflight=ready();preflight['checks']['named_enforcing_profile_identity']='NOT VERIFIED'
            def compile(parser,path):path.write_bytes(b'binary');return dict(binary_sha256=hashlib.sha256(b'binary').hexdigest(),expanded_sha256='e'*64)
            with patch.object(a.os,'geteuid',return_value=0),patch.object(a,'verify_package'),patch.object(a,'trusted_parser',return_value='/trusted/parser'),patch.object(a,'inventory',return_value=before),patch.object(a,'readonly_preflight',return_value=preflight),patch.object(a,'read',return_value='CapEff:\t200000000'),patch.object(a.os,'access',return_value=True),patch.object(a,'state_directory',return_value=directory),patch.object(a,'compile_host_profile',side_effect=compile),patch.object(a,'command') as command,patch.object(a,'verify_job',return_value=ready()):
                self.assertEqual(a.prepare_job('123-1')['status'],'PASS')
            args=command.call_args.args[0]
            self.assertIn('--add',args);self.assertIn('--binary',args);self.assertNotIn('--replace',args)
            self.assertEqual(args[-1],str(directory/'profile.bin'))
            self.assertTrue(json.loads((directory/'receipt.json').read_text())['owned'])
    def test_unprivileged_receipt_query_never_prepares_or_cleans(self):
        with patch.dict(os.environ,{'C3C_POLICY_JOB':'123-1'}),patch.object(a,'command',return_value=json.dumps(ready()).encode()) as command:
            self.assertEqual(a.privileged_receipt(),ready())
        self.assertEqual(command.call_args.args[0][-2:],['--verify-job','123-1'])
        self.assertIn('-I',command.call_args.args[0])
        # Cover the actual hosted delegation separately with an explicit receipt fixture.
        with patch.dict(os.environ,{'C3C_POLICY_JOB':'123-1'}),patch.object(a.os,'geteuid',return_value=1001),patch.object(a,'privileged_receipt',return_value=ready()) as receipt:
            self.assertEqual(a.readonly_preflight(),ready())
            self.assertEqual(a.require_ready(ready()),'b'*64)
            self.assertEqual(receipt.call_count,2)
            changed=ready();changed['evidence']['docker_default_profile_identity']='f'*64
            receipt.return_value=changed
            with self.assertRaises(a.Blocked):a.require_ready(ready())
            receipt.side_effect=a.Blocked('No prepared receipt')
            with self.assertRaises(a.Blocked):a.readonly_preflight()
    def test_missing_or_insecure_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory,state=self.state(folder);directory.chmod(0o755)
            with patch.object(a,'state_directory',return_value=directory),self.assertRaises(a.Blocked):a.read_state('123-1')
    def test_loaded_hash_mismatch_blocks_before_readiness(self):
        with tempfile.TemporaryDirectory() as folder:
            directory,state=self.state(folder)
            with patch.object(a,'read_state',return_value=(directory,state)),patch.object(a,'state_directory',return_value=directory),patch.object(a,'loaded_profile',return_value='f'*64),patch.object(a,'readonly_preflight') as preflight:
                with self.assertRaises(a.Blocked):a.verify_job('123-1')
            preflight.assert_not_called()
    def test_changed_default_identity_is_fail_closed(self):
        with patch.object(a,'inventory',return_value={'docker-default':{'mode':'enforce','sha256':'f'*64}}),self.assertRaises(a.Blocked):
            a.preserve_profiles({'docker-default':{'mode':'enforce','sha256':'c'*64}})
    def test_cleanup_removes_only_receipted_binary_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            directory,state=self.state(folder)
            current=dict(state['before']);current[a.policy.PROFILE]=dict(mode='enforce',sha256=state['compiled']['binary_sha256'])
            def execute(args,**kwargs):return (a.policy.PROFILE+'\n').encode() if '--names' in args else b''
            with patch.object(a,'read_state',return_value=(directory,state)),patch.object(a,'state_directory',return_value=directory),patch.object(a,'inventory',side_effect=[current,state['before'],state['before']]),patch.object(a,'loaded_profile',return_value=state['compiled']['binary_sha256']),patch.object(a,'trusted_parser',return_value='/trusted/parser'),patch.object(a,'command',side_effect=execute) as command:
                result=a.cleanup_job('123-1')
            self.assertTrue(result['owned_profile_removed']);self.assertFalse(directory.exists())
            calls=[c.args[0] for c in command.call_args_list]
            self.assertEqual(calls[2],['/trusted/parser','--config-file','/dev/null','--skip-cache','--jobs','1','--max-jobs','1','--remove',str(directory/'remove.apparmor')])
            self.assertIn('--names',calls[1]);self.assertNotIn('--binary',calls[2])
    def test_cleanup_refuses_unreceipted_policy_after_uncertain_load(self):
        with tempfile.TemporaryDirectory() as folder:
            directory,state=self.state(folder,False)
            current=dict(state['before']);current[a.policy.PROFILE]=dict(mode='enforce',sha256=state['compiled']['binary_sha256'])
            with patch.object(a,'read_state',return_value=(directory,state)),patch.object(a,'state_directory',return_value=directory),patch.object(a,'inventory',return_value=current),patch.object(a,'command') as command:
                with self.assertRaises(a.Blocked):a.cleanup_job('123-1')
            command.assert_not_called();self.assertTrue(directory.exists())
    def test_attached_container_prevents_profile_unload(self):
        with tempfile.TemporaryDirectory() as folder:
            directory,state=self.state(folder)
            current=dict(state['before']);current[a.policy.PROFILE]=dict(mode='enforce',sha256=state['compiled']['binary_sha256'])
            with patch.object(a,'read_state',return_value=(directory,state)),patch.object(a,'state_directory',return_value=directory),patch.object(a,'inventory',return_value=current),patch.object(a,'command',side_effect=[b'abc',json.dumps([{'AppArmorProfile':a.policy.PROFILE}]).encode()]) as command:
                with self.assertRaises(a.Blocked):a.cleanup_job('123-1')
            self.assertEqual(command.call_count,2)
    def test_empty_browser_output_never_counts_as_pass(self):
        with self.assertRaises(AssertionError):run.browser_evidence(b'')
    def test_native_gate_evidence_requires_negative_then_positive_chain(self):
        stages=['setns_invalid_fd','mount_null_target','outer_chroot','unshare_zero','unshare_mount_namespace','user_namespace_chain','full_namespace_chain']
        record=dict(status='PASS',checks=[dict(stage=s,status='PASS') for s in stages])
        lines=['C3C_NAMESPACE_DIAGNOSTIC '+json.dumps(record)]
        lines+=['C3C_BROWSER_DIAGNOSTIC '+json.dumps(dict(kind=k,status=v)) for k,v in [('launch','STARTED'),('sandbox_page','PASS'),('synthetic_dom','PASS')]]
        lines+=['C3C_BROWSER_DIAGNOSTIC '+json.dumps(dict(kind='task_resources',phase='acceptance_complete',status='PASS',evidence=dict(cgroup={'pids.max':'128','pids.peak':'90','pids.events':{'max':'0'}})))]
        self.assertEqual(len(run.browser_evidence('\n'.join(lines).encode())),6)
        record['checks'][0]['status']='FAIL';lines[0]='C3C_NAMESPACE_DIAGNOSTIC '+json.dumps(record)
        with self.assertRaises(AssertionError):run.browser_evidence('\n'.join(lines).encode())
    def test_job_cleanup_has_no_global_managed_selector(self):
        nonce='a'*32;run.OWNED_NONCES.add(nonce)
        with patch.object(run,'command',return_value='') as command:
            self.assertTrue(run.final_cleanup()['zero_job_owned_containers'])
        for call in command.call_args_list:
            self.assertIn('label=seo.c3c.job='+nonce,call.args[0])
        env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='SEOAuditSuite/SEO-Audit-Suite',GITHUB_REF='refs/heads/'+run.BRANCH,GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_ID='123',C3C_POLICY_JOB='123-1')
        with patch.dict(os.environ,env),patch('sys.argv',['run.py','--cleanup']),patch.object(run,'safety',side_effect=RuntimeError('remote changed')) as safety,patch.object(run,'final_cleanup',return_value={'owned_only':True}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(),0)
        safety.assert_not_called()
    def test_foreign_container_cleanup_identity_is_rejected(self):
        nonce='a'*32;run.OWNED_NONCES.add(nonce)
        row=dict(Name='/foreign',Config=dict(Labels={'seo.c3c.job':nonce,'seo.c3c.managed':'true'}))
        with patch.object(run,'command',side_effect=['foreign-id',json.dumps([row])]) as command:
            with self.assertRaises(RuntimeError):run.final_cleanup()
        self.assertEqual(command.call_count,2)
    def test_daemon_error_is_never_absence_or_cleanup_ownership(self):
        import subprocess
        def fail(args,**kwargs):
            kwargs['stderr'].write(b'Cannot connect to the Docker daemon')
            return subprocess.CompletedProcess(args,1)
        with patch.object(run.subprocess,'run',side_effect=fail):
            with self.assertRaises(RuntimeError):run.image_exists('c3c-worker:local')
        self.assertFalse(run.OWNED_IMAGES)
    def test_preexisting_container_is_never_adopted(self):
        args=run.browser_options(IMAGE,'a'*32)[1:]
        with patch.object(run,'ownership_path',return_value=Path('/synthetic/job')),patch.object(run,'object_absent',return_value=False):
            with self.assertRaises(RuntimeError):run.remember_container(args)
        self.assertFalse(run.OWNED_NONCES)
    def test_foreign_volume_is_never_recorded_or_created(self):
        with patch.object(run,'require_absent_object',side_effect=RuntimeError('collision')),patch.object(run.subprocess,'run') as execute:
            with self.assertRaises(RuntimeError):run.command(['docker','volume','create','--label','seo.c3c.job='+'a'*32,'--label','seo.c3c.managed=true','c3c-'+'a'*32+'-ipc'])
        execute.assert_not_called();self.assertFalse(run.OWNED_NONCES)
    def test_broker_does_not_run_after_browser_negative_failure(self):
        source=Path(run.__file__).read_text()
        self.assertIn("if browser['status']=='PASS':stage('native_container_broker_ipc'",source)
        probe=(run.ROOT/'validation/c3c/sandbox_probe.py').read_text()
        self.assertLess(probe.index('    run_checks()'),probe.index("browser=progress.call('browser_launch'"))
    def test_all_outer_capability_sets_must_be_empty(self):
        status='Seccomp:\t2\nNoNewPrivs:\t1\n'+''.join(n+':\t'+('1' if n=='CapPrm' else '0')+'\n' for n in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'))
        def read(path):return a.policy.PROFILE+' (enforce)' if str(path).endswith('/attr/current') else status
        with patch.object(ns.os,'getuid',return_value=10001),patch.object(ns.os,'getgid',return_value=10001),patch.object(ns.Path,'is_file',return_value=True),patch.object(ns.Path,'iterdir',return_value=iter([Path('/synthetic/task')])),patch.object(ns.Path,'read_text',autospec=True,side_effect=read):
            with self.assertRaises(RuntimeError):ns.guard()
    def test_unchanged_workflow_scope_and_always_cleanup_order(self):
        text=(run.ROOT/'.github/workflows/c3c-security-validation.yml').read_text()
        self.assertEqual(text.count('runs-on: ubuntu-24.04'),1)
        self.assertEqual(text.count('  validate:'),1)
        self.assertIn(run.DIAGNOSTIC_PARENT,text);self.assertIn('github.event.repository.private == false',text)
        self.assertEqual(text.count('if: always()'),2)
        self.assertEqual(text.count('timeout-minutes: 1\n'),3)
        self.assertIn('780s python',text);self.assertEqual(text.count('60s sudo'),2)
        # Command/action budgets, including kill grace, leave room inside the unchanged 20-minute job.
        self.assertLess(3*60+(60+5)+(780+30)+2*(60+5),20*60)
        self.assertLess(text.index('--prepare-job'),text.index('--execute'));self.assertLess(text.index('run.py --cleanup'),text.index('--cleanup-job'))
        for forbidden in ('upload-artifact','actions/cache','workflow_dispatch','seccomp=unconfined','--no-sandbox','--replace','apt-get','cache:'):
            self.assertNotIn(forbidden,text)


class CleanupRecoveryTests(unittest.TestCase):
    """Mocked kernel/parser lifecycle only; no native removal claim."""
    def setUp(self):
        self.folder=self.enterContext(tempfile.TemporaryDirectory())
        self.directory=Path(self.folder)/'owned';self.directory.mkdir()
        self.binary=b'synthetic identity';(self.directory/'profile.bin').write_bytes(self.binary)
        self.before={'docker-default':dict(mode='enforce',sha256='c'*64)}
        self.state=dict(job='123-1',profile=a.policy.PROFILE,owned=True,phase='loaded',before=self.before,
                        compiled=dict(binary_sha256=hashlib.sha256(self.binary).hexdigest()))
        self.current=copy.deepcopy(self.before);self.current[a.policy.PROFILE]=dict(mode='enforce',sha256=self.state['compiled']['binary_sha256'])
        self.enterContext(patch.object(a.os,'O_NOFOLLOW',getattr(os,'O_NOFOLLOW',0),create=True))
        self.enterContext(patch.object(a,'state_directory',return_value=self.directory))
        self.enterContext(patch.object(a,'read_state',side_effect=lambda job:(self.directory,self.state)))
        self.enterContext(patch.object(a,'inventory',side_effect=lambda:copy.deepcopy(self.current)))
        self.enterContext(patch.object(a,'loaded_profile',side_effect=lambda name:self.current[name]['sha256']))
        self.enterContext(patch.object(a,'trusted_parser',return_value='/trusted/parser'))
        self.commands=self.enterContext(patch.object(a,'command',side_effect=self.execute))
        self.writes=self.enterContext(patch.object(a,'write_state'))
    def execute(self,args,**kwargs):
        if '--names' in args:return (a.policy.PROFILE+'\n').encode()
        if '--remove' in args:self.current.pop(a.policy.PROFILE)
        return b''
    def run_cleanup(self):
        # Minimal fixture receipt, without claiming POSIX receipt permissions on Windows.
        (self.directory/'receipt.json').write_text('{}')
        return a.cleanup_job('123-1')
    def removals(self):return [c.args[0] for c in self.commands.call_args_list if '--remove' in c.args[0]]
    def test_correct_source_removal_and_repeated_cleanup(self):
        self.assertEqual(self.run_cleanup()['status'],'PASS');self.assertEqual(len(self.removals()),1)
        self.assertNotIn('--binary',self.removals()[0]);self.assertTrue(self.removals()[0][-1].endswith('remove.apparmor'))
        self.assertEqual(a.cleanup_job('123-1')['status'],'PASS');self.assertEqual(len(self.removals()),1)
    def test_identity_mismatch_never_removes(self):
        self.current[a.policy.PROFILE]['sha256']='f'*64
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.commands.assert_not_called()
    def test_preexisting_target_never_removed_even_with_owned_receipt(self):
        self.state['before'][a.policy.PROFILE]=self.current[a.policy.PROFILE]
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.commands.assert_not_called()
    def test_unload_failure_retains_receipt_and_no_success(self):
        def execute(args,**kwargs):
            if '--remove' in args:raise a.Blocked('parser failed')
            return self.execute(args,**kwargs)
        self.commands.side_effect=execute
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.assertTrue((self.directory/'receipt.json').exists());self.assertEqual(self.state['phase'],'removal_pending')
    def test_success_exit_without_absence_is_not_success(self):
        self.commands.side_effect=lambda args,**kw:(a.policy.PROFILE+'\n').encode() if '--names' in args else b''
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.assertTrue(self.directory.exists())
    def test_partial_remove_then_parser_error_can_verify_absence_on_retry(self):
        def execute(args,**kwargs):
            result=self.execute(args,**kwargs)
            if '--remove' in args:raise a.Blocked('lost response after removal')
            return result
        self.commands.side_effect=execute
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.commands.side_effect=self.execute
        self.assertEqual(a.cleanup_job('123-1')['status'],'PASS');self.assertEqual(len(self.removals()),1)
    def test_replacement_after_partial_cleanup_never_removed(self):
        self.state['phase']='removal_pending';self.current[a.policy.PROFILE]['sha256']='f'*64
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.commands.assert_not_called()
    def test_ambiguous_or_foreign_source_names_never_removed(self):
        self.commands.side_effect=lambda args,**kw:b'foreign\n' if '--names' in args else b''
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.assertFalse(self.removals())
    def test_preexisting_change_after_removal_fails_closed(self):
        def execute(args,**kwargs):
            result=self.execute(args,**kwargs)
            if '--remove' in args:self.current['docker-default']['sha256']='f'*64
            return result
        self.commands.side_effect=execute
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.assertTrue((self.directory/'receipt.json').exists())
    def test_private_binary_change_never_removed(self):
        (self.directory/'profile.bin').write_bytes(b'changed')
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.commands.assert_not_called()
    def test_identity_change_between_names_and_unload_never_removed(self):
        with patch.object(a,'loaded_profile',return_value='f'*64):
            with self.assertRaises(a.Blocked):self.run_cleanup()
        self.assertFalse(self.removals())
    def test_unexplained_absence_before_unload_intent_is_failure(self):
        self.current.pop(a.policy.PROFILE)
        with self.assertRaises(a.Blocked):self.run_cleanup()
        self.commands.assert_not_called()
    def test_partial_private_file_cleanup_retries_without_second_unload(self):
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path.name=='remove.apparmor':raise OSError('synthetic private-file cleanup failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',autospec=True,side_effect=unlink):
            with self.assertRaises(OSError):self.run_cleanup()
        self.assertFalse((self.directory/'profile.bin').exists())
        self.assertTrue((self.directory/'receipt.json').exists())
        self.assertEqual(a.cleanup_job('123-1')['status'],'PASS');self.assertEqual(len(self.removals()),1)



class PIDBudgetCompatibilityTests(unittest.TestCase):
    def test_production_budget_and_upper_bound_unchanged(self):
        from deployment.c3c.policy import Limits
        self.assertEqual(Limits().pids,64)
        self.assertEqual(Limits(pids=128).pids,128)
        for value in (0,-1,129,True,'max'):
            with self.assertRaises(ValueError):Limits(pids=value)
    def test_browser_command_and_readback_agree(self):
        args=run.browser_options(IMAGE,'a'*32)
        self.assertEqual(args[args.index('--pids-limit')+1],'128')
        with patch.object(a,'require_ready'):
            a.attach_worker(args,ready());a.verify_container(details(),ready())
    def test_wrong_or_unlimited_worker_budget_rejected(self):
        for value in ('64','0','-1','129','max'):
            args=run.browser_options(IMAGE,'a'*32);args[args.index('--pids-limit')+1]=value
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.attach_worker(args,ready())
        for value in (64,0,-1,129,None):
            info=details();info['HostConfig']['PidsLimit']=value
            with patch.object(a,'require_ready'),self.assertRaises(a.Blocked):a.verify_container(info,ready())
    def modeled_negative(self,record=None,override=None,stderr=b'',exit_code=0,preflight_override=None,timeout=False,identity_failure_at=None):
        import subprocess
        info=details();info['AppArmorProfile']='docker-default'
        info['HostConfig']['SecurityOpt']=['no-new-privileges=true','apparmor=docker-default']
        info['Config']['Cmd']=['-c',run.PID_BUDGET_PROBE]
        if override:override(info)
        record=record or dict(status='PASS',pids_max=128,at_denial=128,event_delta=1,errno=11,owned_children_reaped=True)
        preflight=dict(phase='before_saturation',effective_apparmor_label='docker-default (enforce)',uid=10001,pids_max=128)
        if preflight_override:preflight.update(preflight_override)
        calls=[]
        def command(args,**kw):
            calls.append(args)
            if args[:2]==['docker','inspect']:return json.dumps([info])
            return ''
        def execute(args,**kw):
            calls.append(args)
            kw['stdout'].write((json.dumps(preflight)+'\n'+json.dumps(record)+'\n').encode())
            kw['stderr'].write(stderr)
            if timeout:raise subprocess.TimeoutExpired(args,15)
            return subprocess.CompletedProcess(args,exit_code)
        identities=[]
        def identity(host):
            identities.append(host)
            if len(identities)==identity_failure_at:raise a.Blocked('synthetic profile identity drift')
        with patch.object(run,'command',side_effect=command),patch.object(run.subprocess,'run',side_effect=execute),patch.object(a,'readonly_preflight',return_value=ready()),patch.object(a,'require_ready',side_effect=identity):
            try:return run.native_pid_budget(IMAGE),None,calls
            except (AssertionError,RuntimeError,ValueError) as error:return None,error,calls
    def test_new_budget_negative_fixture_and_owned_cleanup(self):
        result,error,calls=self.modeled_negative()
        self.assertIsNone(error);self.assertEqual(result['at_denial'],128)
        create=calls[0];self.assertIn(run.PID_BUDGET_PROBE,create)
        self.assertNotIn('--privileged',create)
        self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_python_failure_without_pid_event_is_not_enforcement(self):
        record=dict(status='PASS',pids_max=128,at_denial=128,event_delta=0,errno=11,owned_children_reaped=True)
        _,error,calls=self.modeled_negative(record)
        self.assertIsNotNone(error);self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_memory_or_permission_failure_never_claims_pid_pass(self):
        for code in (1,12):
            record=dict(status='PASS',pids_max=128,at_denial=128,event_delta=1,errno=code,owned_children_reaped=True)
            self.assertIsNotNone(self.modeled_negative(record)[1])
    def test_negative_fixture_wrong_readback_blocks_start_and_cleans(self):
        _,error,calls=self.modeled_negative(override=lambda d:d['HostConfig'].update(PidsLimit=0))
        self.assertIsNotNone(error);self.assertFalse(any(c[:2]==['docker','start'] for c in calls))
        self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_unconfined_negative_fixture_is_rejected(self):
        self.assertIsNotNone(self.modeled_negative(override=lambda d:d.update(AppArmorProfile='unconfined'))[1])
    def test_child_cleanup_uncertainty_is_not_pass(self):
        record=dict(status='PASS',pids_max=128,at_denial=128,event_delta=1,errno=11,owned_children_reaped=False)
        self.assertIsNotNone(self.modeled_negative(record)[1])
    def test_saturation_code_is_bounded_and_reaps_only_its_children(self):
        compile(run.PID_BUDGET_PROBE,'PID_BUDGET_PROBE','exec')
        self.assertIn('range(128)',run.PID_BUDGET_PROBE)
        self.assertIn('delta>0',run.PID_BUDGET_PROBE)
        self.assertIn('for pid in children:os.waitpid(pid,0)',run.PID_BUDGET_PROBE)
        self.assertNotIn('setrlimit',run.PID_BUDGET_PROBE)
    def test_explicit_default_profile_only_on_negative_fixture(self):
        args=run.pid_fixture_options(IMAGE,'a'*32)
        self.assertEqual(args.count('apparmor=docker-default'),1)
        self.assertNotIn('apparmor=docker-default',run.browser_options(IMAGE,'a'*32))
        self.assertNotIn('--privileged',args);self.assertNotIn('seccomp=unconfined',args)
    def test_missing_explicit_selection_blocks_before_start(self):
        _,error,calls=self.modeled_negative(override=lambda d:d['HostConfig'].update(SecurityOpt=['no-new-privileges=true']))
        self.assertIn('HostConfig.SecurityOpt',str(error))
        self.assertFalse(any(c[:2]==['docker','start'] for c in calls))
    def test_empty_creation_metadata_is_not_accepted_as_default(self):
        _,error,calls=self.modeled_negative(override=lambda d:d.update(AppArmorProfile=''))
        self.assertIn("AppArmorProfile expected='docker-default' observed=''",str(error))
        self.assertFalse(any(c[:2]==['docker','start'] for c in calls))
    def test_other_profile_identity_blocks_start(self):
        _,error,calls=self.modeled_negative(override=lambda d:d.update(AppArmorProfile='foreign-profile'))
        self.assertIn('AppArmorProfile',str(error));self.assertIn('foreign-profile',str(error))
        self.assertFalse(any(c[:2]==['docker','start'] for c in calls))
    def test_pid_readback_error_names_field_expected_and_observed(self):
        _,error,_=self.modeled_negative(override=lambda d:d['HostConfig'].update(PidsLimit=64))
        self.assertIn('HostConfig.PidsLimit expected=128 observed=64',str(error))
    def test_preflight_complain_mode_is_rejected(self):
        self.assertIsNotNone(self.modeled_negative(preflight_override=dict(effective_apparmor_label='docker-default (complain)'))[1])
    def test_payload_checks_kernel_label_before_fork(self):
        from unittest.mock import Mock
        fork=Mock(side_effect=AssertionError('fork must not run'))
        with patch.object(run.os,'getuid',return_value=10001),patch.object(run.os,'getgid',return_value=10001),patch.object(Path,'open',return_value=io.StringIO('docker-default (complain)')),patch.object(run.os,'fork',fork):
            with self.assertRaisesRegex(AssertionError,'effective_apparmor_label'):
                exec(compile(run.PID_BUDGET_PROBE,'pid-fixture','exec'),{})
        fork.assert_not_called()
    def test_bad_host_hash_blocks_before_create(self):
        host=ready();host['evidence']['docker_default_profile_identity']='unknown'
        with patch.object(a,'readonly_preflight',return_value=host),patch.object(a,'require_ready'),patch.object(run,'command') as command:
            with self.assertRaisesRegex(AssertionError,'docker_default_profile_identity.sha256'):run.native_pid_budget(IMAGE)
        command.assert_not_called()
    def test_host_identity_failure_is_not_bypassed(self):
        with patch.object(a,'readonly_preflight',return_value=ready()),patch.object(a,'require_ready',side_effect=a.Blocked('synthetic hash mismatch')),patch.object(run,'command') as command:
            with self.assertRaises(a.Blocked):run.native_pid_budget(IMAGE)
        command.assert_not_called()
    def test_identity_drift_before_start_blocks_and_cleans(self):
        _,error,calls=self.modeled_negative(identity_failure_at=2)
        self.assertIsNotNone(error);self.assertFalse(any(c[:2]==['docker','start'] for c in calls))
        self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_identity_drift_after_execution_never_counts_as_pass(self):
        _,error,calls=self.modeled_negative(identity_failure_at=3)
        self.assertIsNotNone(error);self.assertTrue(any(c[:2]==['docker','start'] for c in calls))
        self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_execution_stderr_is_redacted_and_exit_is_reported(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):_,error,calls=self.modeled_negative(stderr=b'token=hidden\nfield mismatch',exit_code=1)
        self.assertNotIn('hidden',out.getvalue());self.assertIn('field mismatch',out.getvalue())
        self.assertIn('docker_attach.exit_code expected=0 observed=1',str(error))
        self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_oversized_stderr_is_flagged_and_rejected(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):_,error,_=self.modeled_negative(stderr=b'x'*3000)
        self.assertIn('stderr.within_2048_bytes',str(error))
        self.assertIn('"stderr_truncated": true',out.getvalue())
    def test_timeout_keeps_diagnostics_and_owned_cleanup(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):_,error,calls=self.modeled_negative(timeout=True)
        self.assertIn('docker_attach.timeout',str(error));self.assertIn('"timeout": true',out.getvalue())
        self.assertTrue(any(c[:3]==['docker','rm','--force'] for c in calls))
    def test_field_diagnostics_redact_and_bound(self):
        with self.assertRaises(AssertionError) as caught:run.pid_fixture_equal('profile','docker-default','token=hidden '+('x'*5000))
        self.assertNotIn('hidden',str(caught.exception));self.assertLess(len(str(caught.exception)),260)
    def test_extra_privilege_has_field_specific_error(self):
        _,error,_=self.modeled_negative(override=lambda d:d['HostConfig'].update(CapAdd=['SYS_ADMIN']))
        self.assertIn('HostConfig.CapAdd.empty',str(error))
    def browser_records(self,counters=None):
        stages=['setns_invalid_fd','mount_null_target','outer_chroot','unshare_zero','unshare_mount_namespace','user_namespace_chain','full_namespace_chain']
        records=['C3C_NAMESPACE_DIAGNOSTIC '+json.dumps(dict(status='PASS',checks=[dict(stage=x,status='PASS') for x in stages]))]
        records+=['C3C_BROWSER_DIAGNOSTIC '+json.dumps(dict(kind=k,status=v)) for k,v in [('launch','STARTED'),('sandbox_page','PASS'),('synthetic_dom','PASS')]]
        if counters is not None:records+=['C3C_BROWSER_DIAGNOSTIC '+json.dumps(dict(kind='task_resources',phase='acceptance_complete',status='PASS',evidence=dict(cgroup=counters)))]
        return records
    def test_final_budget_evidence_is_mandatory(self):
        with self.assertRaises(AssertionError):run.browser_evidence('\n'.join(self.browser_records()).encode())
    def test_positive_browser_pid_denial_or_missing_peak_is_not_pass(self):
        for counters in ({'pids.max':'128','pids.peak':'128','pids.events':{'max':'1'}},
                         {'pids.max':'128','pids.events':{'max':'0'}},
                         {'pids.max':'max','pids.peak':'90','pids.events':{'max':'0'}}):
            with self.assertRaises(AssertionError):run.browser_evidence('\n'.join(self.browser_records(counters)).encode())
    def test_positive_budget_does_not_replace_dom_or_sandbox_gates(self):
        for remove in ('sandbox_page','synthetic_dom'):
            rows=self.browser_records({'pids.max':'128','pids.peak':'90','pids.events':{'max':'0'}})
            rows=[x for x in rows if '"kind": "'+remove+'"' not in x]
            with self.assertRaises(AssertionError):run.browser_evidence('\n'.join(rows).encode())
    def test_runtime_snapshot_preserves_budget_evidence(self):
        source=(run.ROOT/'validation/c3c/sandbox_probe.py').read_text()
        self.assertLess(source.index("progress.phase('dom_extraction')"),source.index("phase='acceptance_complete'"))
    def test_original_small_resource_fixture_unchanged(self):
        from deployment.c3c import native_runner
        self.assertIn("'--pids-limit','8'",Path(native_runner.__file__).read_text())
    def test_pid_negative_gate_precedes_positive_browser_and_fails_closed(self):
        source=Path(run.__file__).read_text()
        body=source[source.index('def main():'):]
        self.assertLess(body.index("stage('native_validation_128_task_enforcement'"),body.index("stage('native_candidate_browser_sandbox'"))
        self.assertIn("and budget_check and budget_check['status']=='PASS'",body)

if __name__=='__main__':unittest.main()
