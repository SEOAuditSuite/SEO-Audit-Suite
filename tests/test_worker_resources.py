"""C3B policy, Windows API wiring and honest partial-evidence regressions.

Faked Win32 calls below test wiring only; native enforcement is a separate gate.
"""
import ctypes
import json
import math
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import browser_supervision as bs
import client_workflow as cw
import common
import rendering_diagnostics as rd
import test_browser_supervision as lifecycle


class FakeFunction:
    def __init__(self,fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)


class FakeAPI:
    """Stores exactly what was configured for independent readback comparisons."""
    def __init__(self,fail=None):
        self.fail=fail;self.sets=[];self.closed=[];self.blocks={};self.terminated=0
        self.CreateJobObjectW=FakeFunction(lambda *args:101)
        self.CreateIoCompletionPort=FakeFunction(lambda *args:202)
        self.CloseHandle=FakeFunction(lambda h:self.closed.append(h) or True)
        self.SetInformationJobObject=FakeFunction(self.set)
        self.QueryInformationJobObject=FakeFunction(self.query)
        self.AssignProcessToJobObject=FakeFunction(lambda *args:fail!='assign')
        self.TerminateJobObject=FakeFunction(self.terminate)
        self.GetQueuedCompletionStatus=FakeFunction(lambda *args:False)
    def set(self,h,k,p,size):
        self.sets.append(k);self.blocks[k]=ctypes.string_at(p,size)
        return k!=self.fail
    def query(self,h,k,p,size,*rest):
        if self.fail=='query':return False
        if k in self.blocks:ctypes.memmove(p,self.blocks[k],min(size,len(self.blocks[k])))
        return True
    def terminate(self,*args):self.terminated+=1;return True


class ResourcePolicyTests(unittest.TestCase):
    def test_conservative_starting_defaults(self):
        p=bs.JobLimits();self.assertEqual((p.processes,p.memory_mib,p.cpu_percent),(64,4096,80))
    def test_validated_parent_configuration(self):
        with patch.dict(os.environ,{'SEO_JOB_MAX_PROCESSES':'96','SEO_JOB_MEMORY_MIB':'8192','SEO_JOB_CPU_PERCENT':'90'},clear=True):
            self.assertEqual(bs.JobLimits.from_environment(),bs.JobLimits(96,8192,90))
    def test_invalid_values_never_launch_worker(self):
        for v in ['0','-1','1.5','NaN',' 64','9999999','secret-value','１２']:
            with self.subTest(v=v),patch.dict(os.environ,{'SEO_JOB_MAX_PROCESSES':v}),patch.object(bs.subprocess,'Popen') as p:
                self.assertEqual(bs.run_worker(['worker'],'{}',1).reason,'invalid_resource_policy');p.assert_not_called()
    def test_programmatic_policy_bounds_and_types(self):
        for kwargs in [dict(processes=True),dict(processes=1),dict(processes=257),dict(memory_mib=63),dict(memory_mib=32769),dict(cpu_percent=0),dict(cpu_percent=101)]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):bs.JobLimits(**kwargs)
    def test_deadline_rejected_before_launch(self):
        for value in [0,-1,math.inf,math.nan,True,601,'10']:
            with self.subTest(v=value),patch.object(bs.subprocess,'Popen') as p:
                self.assertEqual(bs.run_worker(['worker'],'{}',value).reason,'invalid_execution_deadline');p.assert_not_called()
    def test_config_is_parent_only_not_forwarded(self):
        self.assertNotIn('SEO_JOB_MEMORY_MIB',bs._worker_environment({'SEO_JOB_MEMORY_MIB':'8192'}))
    def job(self,fail=None):
        api=FakeAPI(fail)
        with patch.object(ctypes,'WinDLL',return_value=api,create=True),patch.object(bs.threading.Thread,'start'):
            job=bs.WindowsJob(SimpleNamespace(_handle=42),bs.JobLimits(16,512,70))
        return job,api
    def test_native_limit_wiring_readback_and_no_breakaway(self):
        job,api=self.job();self.assertEqual(api.sets,[9,15,7]);r=job.resource_snapshot()
        self.assertTrue(r['verified']);self.assertEqual(r['process_limit'],16)
        self.assertEqual(r['committed_memory_limit_bytes'],512*1024*1024)
        self.assertEqual(r['cpu_rate_percent'],70);self.assertEqual(r['cpu_flags'],5)
        self.assertEqual(r['limit_flags'] & 0x1800,0)
        with patch.object(job.monitor_thread,'join'),patch.object(job.monitor_thread,'is_alive',return_value=False):job.close()
        self.assertEqual(api.closed,[101,202])
    def test_readback_mismatch_is_not_verification(self):
        job,api=self.job();api.blocks[15]=b'\0'*len(api.blocks[15]);self.assertFalse(job.resource_snapshot()['verified'])
    def test_failed_cap_port_query_or_assignment_closes_job(self):
        for fail in [9,15,7,'query','assign']:
            api=FakeAPI(fail)
            with self.subTest(fail=fail),patch.object(ctypes,'WinDLL',return_value=api,create=True),self.assertRaises(OSError) as error:
                bs.WindowsJob(SimpleNamespace(_handle=42))
            self.assertIn(101,api.closed)
            self.assertTrue(error.exception.resource_stage.startswith('Worker '))
    def test_resource_event_terminates_only_owned_job(self):
        job,api=self.job()
        def message(port,msg,key,overlap,timeout):
            msg._obj.value=10;key._obj.value=1;job.monitor_stop.set();return True
        api.GetQueuedCompletionStatus=message;job._monitor_resources()
        self.assertEqual(job.resource_events,{'job_memory_limit'});self.assertEqual(api.terminated,1)
    def test_notification_failure_is_fail_closed(self):
        job,api=self.job();api.GetQueuedCompletionStatus=Mock(side_effect=OSError)
        job._monitor_resources();self.assertTrue(job.monitor_failed);self.assertEqual(api.terminated,1)
    def test_resource_event_discards_worker_output_after_cleanup(self):
        p=Mock(returncode=0);p.communicate.return_value=('untrusted-result',None)
        job=Mock(resource_events={'active_process_limit'},monitor_failed=False)
        with patch.object(bs.os,'name','nt'),patch.object(bs.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(bs.subprocess,'Popen',return_value=p),patch.object(bs,'WindowsJob',return_value=job),patch.object(bs,'cleanup_tree',return_value=True):
            r=bs.run_worker(['worker'],'{}',1)
        self.assertEqual(r.reason,'resource_limit');self.assertEqual(r.output,'');self.assertTrue(r.cleanup_confirmed)
    def test_resource_monitor_failure_is_not_success(self):
        p=Mock(returncode=0);p.communicate.return_value=('ok',None)
        with patch.object(bs.os,'name','nt'),patch.object(bs.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(bs.subprocess,'Popen',return_value=p),patch.object(bs,'WindowsJob',return_value=Mock(resource_events=set(),monitor_failed=True)),patch.object(bs,'cleanup_tree',return_value=True):
            self.assertEqual(bs.run_worker(['worker'],'{}',1).reason,'resource_monitor_unavailable')
    def test_resource_stop_preserves_checkpoint_and_unknown_status(self):
        fixture=lifecycle.CrawlDeadlineTests()
        with patch.object(bs,'run_worker',side_effect=fixture.worker('resource_limit')),patch.object(common,'_crawl_site_local') as retry:
            c=common.crawl_site('https://audit.example.test/',limit=2)
        retry.assert_not_called();self.assertEqual(len(c['pages']),2)
        self.assertFalse(c['coverage']['observed_graph_complete']);self.assertIsNone(c['status_checks'][-1]['status'])
        self.assertEqual(c['coverage']['stop_reason'],'resource_limit')
    def test_resource_stop_does_not_create_phase3_missing_elements(self):
        with patch.object(bs,'run_worker',return_value=bs.WorkerResult(reason='resource_limit',cleanup_confirmed=True)):
            r=rd.compare_url('https://audit.example.test/')
        self.assertFalse(r['comparison_available']);self.assertEqual(r['rows'],[])


class ParentInputBoundTests(unittest.TestCase):
    def test_valid_keyword_input_unchanged(self):
        row=cw.parse_keyword_csv(b'Keyword\nexample\n')[0];self.assertEqual(row['Keyword'],'example')
    def test_oversized_bytes_rejected_before_decode(self):
        with patch.object(cw,'KEYWORD_CSV_BYTES',5),self.assertRaisesRegex(ValueError,'5 MiB'):cw.parse_keyword_csv(b'\xff'*6)
    def test_multibyte_text_counted_in_bytes(self):
        with patch.object(cw,'KEYWORD_CSV_BYTES',5),self.assertRaisesRegex(ValueError,'5 MiB'):cw.parse_keyword_csv('\u20ac'*2)
    def test_row_bound_counts_empty_keyword_records(self):
        with patch.object(cw,'KEYWORD_CSV_ROWS',2),self.assertRaisesRegex(ValueError,'10000-row'):cw.parse_keyword_csv('Keyword,Other\n,one\n,two\n,three\n')
    def test_row_boundary_accepted(self):
        with patch.object(cw,'KEYWORD_CSV_ROWS',2):self.assertEqual(len(cw.parse_keyword_csv('Keyword\na\nb\n')),2)
    def test_invalid_input_type_is_actionable(self):
        with self.assertRaisesRegex(ValueError,'text or bytes'):cw.parse_keyword_csv(None)

if __name__=='__main__':unittest.main()
