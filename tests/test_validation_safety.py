"""C3B R2 deterministic safety regressions: no native stress execution here."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import validation_host as vh


def healthy(**changes):
    return dict(dict(available_memory_mib=2048,available_commit_mib=3072,cpu_percent=10),**changes)


class MarkerSafetyTests(unittest.TestCase):
    def test_legacy_truncation_reproduces_reported_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'marker.json';p.write_text('{"stage":"stdin_released"}')
            with p.open('w'):pass  # Termination between truncate and the write.
            with self.assertRaises(json.JSONDecodeError):json.loads(p.read_text())
            self.assertEqual(vh.read_marker(p)['state'],'empty')
    def test_interrupted_atomic_replace_retains_committed_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'marker.json';vh.atomic_json(p,dict(stage='stdin_released'))
            with patch.object(vh.os,'replace',side_effect=OSError('simulated termination')),self.assertRaises(OSError):
                vh.atomic_json(p,dict(stage='commit_attempt'))
            self.assertEqual(vh.read_marker(p)['value']['stage'],'stdin_released')
    def test_partial_pending_file_never_replaces_live_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'marker.json';vh.atomic_json(p,dict(stage='stdin_released'))
            p.with_name(p.name+'.pending').write_text('{')
            self.assertEqual(vh.read_marker(p)['state'],'valid')
            self.assertEqual(vh.read_marker(p)['value']['stage'],'stdin_released')
    def test_missing_empty_partial_and_invalid_schema_are_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'marker.json';self.assertEqual(vh.read_marker(p)['state'],'missing')
            for raw,state in [(b'', 'empty'),(b'  ','empty'),(b'{','invalid_json'),(b'\xff','invalid_json'),(b'[]','invalid_schema'),(b'{}','invalid_schema')]:
                with self.subTest(raw=raw):
                    p.write_bytes(raw);result=vh.read_marker(p)
                    self.assertEqual(result['state'],state);self.assertIsNone(result['value'])
                    self.assertEqual(result['bytes'],len(raw));self.assertEqual(len(result['sha256']),64)
    def test_oversized_marker_is_not_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'marker.json';p.write_bytes(b'x'*65537)
            self.assertEqual(vh.read_marker(p)['state'],'oversized')


class NativeDiagnosticTests(unittest.TestCase):
    def test_empty_marker_keeps_real_termination_evidence_without_json_error(self):
        import windows_c3b_validation as native
        import browser_supervision as bs
        class Guard:
            def preflight(self,stage):return None
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);runs={}
            def supervised(command,payload,seconds,limits):
                request=json.loads(payload);Path(request['marker']).write_bytes(b'')
                return bs.WorkerResult(reason='resource_limit',cleanup_confirmed=True,
                    diagnostics=dict(returncode=1,cleanup=dict(confirmed=True)))
            with patch.object(native.time,'sleep'):
                data=native.exercise_worker(output,'memory','memory',bs.JobLimits(16,128,25),Guard(),runs,supervised)
            self.assertEqual(data['marker_diagnostics']['state'],'empty')
            self.assertIsNone(data['marker']);self.assertEqual(data['reason'],'resource_limit')
            self.assertEqual(data['stdout_bytes'],0)
            self.assertEqual(json.loads((output/'memory-worker.json').read_text())['diagnostics']['returncode'],1)
    def test_unconfirmed_cleanup_stops_after_diagnostics_are_saved(self):
        import windows_c3b_validation as native
        import browser_supervision as bs
        class Guard:
            def preflight(self,stage):raise AssertionError('must not continue')
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);runs={}
            with self.assertRaisesRegex(RuntimeError,'cleanup unconfirmed'):
                native.exercise_worker(output,'failed','memory',bs.JobLimits(16,128,25),Guard(),runs,
                    lambda *a,**k:bs.WorkerResult(reason='worker_crashed',cleanup_confirmed=False))
            self.assertEqual(runs['failed']['marker_diagnostics']['state'],'missing')
            self.assertTrue((output/'failed-worker.json').exists())


class HostSafetyTests(unittest.TestCase):
    def test_low_profile_is_distinct_from_production_defaults(self):
        import browser_supervision as bs
        self.assertEqual(vh.LOW_PROFILE,dict(processes=32,memory_mib=1024,cpu_percent=25))
        self.assertEqual(bs.JobLimits().memory_mib,4096)
        self.assertLess(vh.LOW_PROFILE['memory_mib'],bs.JobLimits().memory_mib)
    def test_preflight_requires_available_memory_not_installed_memory(self):
        self.assertEqual(vh.assess_host(healthy(),True),'')
        self.assertIn('available_memory',vh.assess_host(healthy(available_memory_mib=1535),True))
        self.assertIn('available_commit',vh.assess_host(healthy(available_commit_mib=2047),True))
    def test_cpu_busy_and_missing_accounting_block_preflight(self):
        for v in [61,None,float('nan'),-1,101]:
            self.assertTrue(vh.assess_host(healthy(cpu_percent=v),True))
    def test_runtime_memory_guard_is_fail_closed(self):
        self.assertTrue(vh.assess_host(healthy(available_memory_mib=767)))
        self.assertTrue(vh.assess_host(healthy(available_commit_mib=1023)))
        self.assertTrue(vh.assess_host(healthy(available_memory_mib=float('nan'))))
    def test_cpu_delta_excludes_idle_kernel_time(self):
        self.assertAlmostEqual(vh.cpu_usage((10,20,10),(20,40,20)),100*20/30)
    def test_invalid_cpu_counter_delta_not_reported_idle(self):
        for before,after in [((1,2,3),(1,2,3)),((1,2,3),(0,3,4)),((0,0,0),(100,1,1))]:
            with self.subTest(after=after),self.assertRaises(RuntimeError):vh.cpu_usage(before,after)
    def test_sustained_pressure_stops_and_records_reason(self):
        class Probe:
            def sample(self):return healthy(cpu_percent=90)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'host.jsonl';guard=vh.HostGuard(p,Probe())
            guard.observe('test');guard.observe('test')
            with self.assertRaisesRegex(RuntimeError,'sustained'):guard.observe('test')
            records=[json.loads(v) for v in p.read_text().splitlines()]
            self.assertEqual(len(records),3);self.assertIn('NOT VERIFIED',records[-1]['stop_reason'])
    def test_cpu_pressure_counter_recovers_after_idle(self):
        class Probe:
            def __init__(self):self.values=iter([90,10,90])
            def sample(self):return healthy(cpu_percent=next(self.values))
        with tempfile.TemporaryDirectory() as tmp:
            guard=vh.HostGuard(Path(tmp)/'host.jsonl',Probe())
            for _ in range(3):guard.observe('test')
            self.assertEqual(guard.high_cpu,1)
    def test_native_fixture_retains_diagnostics_before_marker_check(self):
        import windows_c3b_validation as native
        import inspect
        source=inspect.getsource(native.exercise_worker)
        self.assertNotIn('json.loads(marker.read_text()',source)
        self.assertIn("data['marker_diagnostics']=read_marker(marker)",source)
        self.assertIn("atomic_json(output/(name+'-worker.json'),data)",source)
        self.assertNotIn('bs.JobLimits(64,1024,100)',source)
    def test_no_multicore_cpu_stress_fixture(self):
        import windows_c3b_validation as native
        import inspect
        code=inspect.getsource(native.worker)
        cpu=code.split("elif mode=='cpu':",1)[1]
        self.assertNotIn('subprocess.Popen',cpu)
        self.assertIn('time.monotonic()-started<2',cpu)
        self.assertIn('160*1024*1024',code)


class ValidationLifecycleTests(unittest.TestCase):
    def job(self,fail=None):
        import ctypes
        from types import SimpleNamespace
        from test_worker_resources import FakeAPI
        api=FakeAPI(fail)
        with patch.object(ctypes,'WinDLL',return_value=api,create=True):
            job=vh.ValidationStageJob(SimpleNamespace(_handle=42))
        return job,api
    def test_stage_job_caps_commit_and_processes_without_distorting_cpu_quota(self):
        job,api=self.job()
        self.assertEqual(api.sets,[9]);self.assertEqual(job.limits['committed_memory_mib'],1536)
        self.assertEqual(job.limits['processes'],64)
        self.assertEqual(int.from_bytes(api.blocks[9][16:20],'little'),0x2208)
        result=job.cleanup()
        self.assertTrue(result['confirmed']);self.assertEqual(result['after']['active_processes'],0)
        self.assertEqual(api.closed,[101])
    def test_stage_assignment_failure_closes_job_before_command_release(self):
        import ctypes
        from types import SimpleNamespace
        from test_worker_resources import FakeAPI
        api=FakeAPI('assign')
        with patch.object(ctypes,'WinDLL',return_value=api,create=True),self.assertRaisesRegex(RuntimeError,'input gate remains closed'):
            vh.ValidationStageJob(SimpleNamespace(_handle=42))
        self.assertEqual(api.closed,[101])
    def test_stage_query_failure_never_claims_tree_cleanup(self):
        job,api=self.job();api.fail='query'
        with patch.object(vh.time,'monotonic',side_effect=[0,6]):result=job.cleanup()
        self.assertFalse(result['confirmed']);self.assertEqual(api.closed,[101])


class GuardedStageTests(unittest.TestCase):
    def test_serial_stage_rejects_concurrent_execution(self):
        with patch.object(vh,'_stage_running',True),self.assertRaisesRegex(RuntimeError,'serial execution'):
            vh.run_guarded_stage([],None,None,None,1,object())
    def test_stage_assigns_job_before_command_input_and_cleans_after_success(self):
        from unittest.mock import Mock
        order=[];process=Mock();process.poll.return_value=0;process.wait.return_value=0
        process.stdin.write.side_effect=lambda value:order.append('input')
        guard=Mock();job=Mock();job.cleanup.return_value=dict(confirmed=True,after=dict(active_processes=0))
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'stage.log'
            with patch.object(vh.subprocess,'Popen',return_value=process),patch.object(vh,'ValidationStageJob',side_effect=lambda p:order.append('job') or job),patch.object(vh.time,'sleep'):
                self.assertEqual(vh.run_guarded_stage(['python','test'],log,Path(tmp),{},5,guard),0)
            self.assertEqual(order,['job','input']);job.cleanup.assert_called_once()
            self.assertTrue(json.loads((Path(tmp)/'stage-stage-cleanup.json').read_text())['confirmed'])
    def test_pressure_stop_cleans_owned_stage_and_does_not_pass(self):
        import subprocess
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=None;process.wait.side_effect=[subprocess.TimeoutExpired('stage',1),0]
        guard=Mock();guard.observe.side_effect=RuntimeError('NOT VERIFIED: pressure')
        job=Mock();job.cleanup.return_value=dict(confirmed=True)
        with tempfile.TemporaryDirectory() as tmp,patch.object(vh.subprocess,'Popen',return_value=process),patch.object(vh,'ValidationStageJob',return_value=job):
            log=Path(tmp)/'stage.log'
            with self.assertRaisesRegex(RuntimeError,'pressure'):vh.run_guarded_stage(['python','test'],log,Path(tmp),{},5,guard)
            job.cleanup.assert_called_once();self.assertFalse(vh._stage_running)
            self.assertIn('pressure',json.loads((Path(tmp)/'stage-stage-cleanup.json').read_text())['stop_reason'])
    def test_operator_cancellation_cleans_owned_stage_and_propagates(self):
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=None;process.wait.side_effect=[KeyboardInterrupt(),0]
        guard=Mock();job=Mock();job.cleanup.return_value=dict(confirmed=True)
        with tempfile.TemporaryDirectory() as tmp,patch.object(vh.subprocess,'Popen',return_value=process),patch.object(vh,'ValidationStageJob',return_value=job):
            with self.assertRaises(KeyboardInterrupt):vh.run_guarded_stage(['python','test'],Path(tmp)/'cancel.log',Path(tmp),{},5,guard)
        job.cleanup.assert_called_once();self.assertFalse(vh._stage_running)

if __name__=='__main__':unittest.main()
