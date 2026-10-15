"""R2 guards against confusing navigation timeout with the hard worker deadline."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import browser_supervision as bs
import browser_c2b_validation as fixture


def observed():
    crawl=dict(coverage=dict(stop_reason='execution_deadline'),browser_supervision=dict(cleanup_confirmed=True))
    diagnostics=dict(stop_reason='execution_deadline',deadline_seconds=10,elapsed_seconds=10.1,worker_pid=100,
        cleanup=dict(method='windows_job',confirmed=True,
            before=dict(available=True,membership_complete=True,active_processes=3,pids=[100,101,102]),
            after=dict(available=True,membership_complete=True,active_processes=0,pids=[])))
    events=[dict(stage='navigation_started',timeout_ms=30000),dict(stage='infinite_script_started'),dict(stage='secure_browser_started',driver_pid=101)]
    return crawl,diagnostics,events


class DeadlineFixtureTests(unittest.TestCase):
    def test_fixture_has_strict_outer_before_navigation_deadline(self):
        self.assertEqual(fixture.HARD_DEADLINE_SECONDS,10)
        self.assertEqual(fixture.HANG_NAVIGATION_MS,30000)
        self.assertLess(fixture.HARD_DEADLINE_SECONDS,fixture.HANG_NAVIGATION_MS/1000)

    def test_real_deadline_and_complete_job_evidence_satisfy_both_checks(self):
        evidence=observed()
        self.assertTrue(fixture.hard_deadline_observed(*evidence))
        self.assertTrue(fixture.timeout_tree_observed(*evidence))

    def test_original_windows_navigation_timeout_is_not_hard_deadline(self):
        c,d,e=observed();c['coverage']['stop_reason']='queue_exhausted_with_errors';c.pop('browser_supervision')
        d.update(stop_reason='',elapsed_seconds=6);e[0]['timeout_ms']=5000
        self.assertFalse(fixture.hard_deadline_observed(c,d,e))
        self.assertFalse(fixture.timeout_tree_observed(c,d,e))

    def test_worker_launch_hang_without_script_execution_is_not_browser_proof(self):
        c,d,e=observed();e=[row for row in e if row['stage']!='infinite_script_started']
        self.assertFalse(fixture.hard_deadline_observed(c,d,e))

    def test_early_or_unbounded_elapsed_time_fails_deadline_evidence(self):
        for elapsed in [5,30]:
            c,d,e=observed();d['elapsed_seconds']=elapsed
            self.assertFalse(fixture.hard_deadline_observed(c,d,e))

    def test_cleanup_boolean_without_kernel_job_membership_is_insufficient(self):
        c,d,e=observed();d['cleanup']['before']=None
        self.assertFalse(fixture.timeout_tree_observed(c,d,e))

    def test_remaining_process_or_incomplete_job_list_fails_cleanup_evidence(self):
        c,d,e=observed();d['cleanup']['after'].update(active_processes=1,pids=[102])
        self.assertFalse(fixture.timeout_tree_observed(c,d,e))
        c,d,e=observed();d['cleanup']['before']['membership_complete']=False
        self.assertFalse(fixture.timeout_tree_observed(c,d,e))

    def test_worker_and_playwright_driver_must_belong_to_same_owned_job(self):
        for missing in [100,101]:
            c,d,e=observed();d['cleanup']['before']['pids'].remove(missing)
            self.assertFalse(fixture.timeout_tree_observed(c,d,e))


class JobDiagnosticTests(unittest.TestCase):
    def job(self,active,pids,assigned=None,fail=False):
        class Accounting(ctypes.Structure):
            _fields_=[('Active',ctypes.c_ulong)]
        job=bs.WindowsJob.__new__(bs.WindowsJob);job.ctypes=ctypes;job.Accounting=Accounting;job.handle=123
        def query(handle,kind,ptr,size,length):
            if fail:return 0
            obj=ptr._obj
            if kind==1:obj.Active=active
            else:
                obj.Assigned=len(pids) if assigned is None else assigned;obj.Listed=len(pids)
                for i,pid in enumerate(pids):obj.Ids[i]=pid
            return 1
        job.api=Mock();job.api.QueryInformationJobObject.side_effect=query
        return job

    def test_job_snapshot_records_members_before_and_zero_after(self):
        before=self.job(3,[100,101,102]).snapshot();after=self.job(0,[]).snapshot()
        self.assertEqual(before['pids'],[100,101,102]);self.assertEqual(before['active_processes'],3)
        self.assertTrue(before['membership_complete']);self.assertTrue(after['membership_complete'])
        self.assertEqual(after['active_processes'],0);self.assertEqual(after['pids'],[])

    def test_failed_job_query_is_unavailable_not_empty_success(self):
        self.assertEqual(self.job(3,[100],fail=True).snapshot(),dict(available=False))

    def test_bounded_job_list_does_not_claim_truncated_membership_complete(self):
        result=self.job(1025,list(range(1024)),assigned=1025).snapshot()
        self.assertEqual(len(result['pids']),1024);self.assertFalse(result['membership_complete'])


class SupervisorDiagnosticTests(unittest.TestCase):
    def test_real_worker_diagnostics_are_serializable_and_match_cleanup(self):
        result=bs.run_worker([sys.executable,'-c','import json,sys; json.load(sys.stdin); print("ok")'],'{}',5)
        self.assertEqual(result.reason,'');self.assertTrue(result.cleanup_confirmed)
        json.dumps(result.diagnostics)
        self.assertGreater(result.diagnostics['worker_pid'],1)
        self.assertTrue(result.diagnostics['cleanup']['confirmed'])
        self.assertGreater(result.diagnostics['elapsed_seconds'],0)

    def test_second_pipe_timeout_preserves_unconfirmed_diagnostics(self):
        process=Mock(pid=123,returncode=None);process.communicate.side_effect=subprocess.TimeoutExpired('worker',5)
        with patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob'),patch.object(bs,'_host_group',return_value=None),patch.object(bs.os,'killpg',create=True):
            result=bs.run_worker(['worker'],'{}',1)
        self.assertEqual(result.reason,'execution_deadline');self.assertFalse(result.cleanup_confirmed)
        self.assertFalse(result.diagnostics['cleanup']['confirmed']);json.dumps(result.diagnostics)


if __name__=='__main__':unittest.main()
