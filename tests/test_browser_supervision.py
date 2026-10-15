"""C2B lifecycle tests; no live websites and no security bypass in production."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import browser_supervision as bs
import common
import rendering_diagnostics as rd
from client_workflow import build_delivery, delivery_files
from link_diagnostics import analyze_links, coverage_note
from test_link_diagnostics import page, BASE
from test_regressions import discovery


def pid_running(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes as w
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
        api.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
        api.CloseHandle.argtypes=[w.HANDLE]
        handle=api.OpenProcess(0x1000,False,pid)
        if not handle: return False
        code=w.DWORD()
        try: return not api.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally: api.CloseHandle(handle)
    try:
        if Path('/proc').is_dir():
            namespace=os.readlink('/proc/self/ns/pid')
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    if os.readlink(entry/'ns/pid') != namespace:continue
                    rows=dict(line.split(':',1) for line in (entry/'status').read_text().splitlines() if ':' in line)
                    if int(rows.get('NSpid', rows['Pid']).split()[-1])==pid:
                        return not rows['State'].strip().startswith('Z')
                except (FileNotFoundError,ProcessLookupError,PermissionError):pass
            return False
        os.kill(pid,0); return True
    except ProcessLookupError: return False


class SupervisorTests(unittest.TestCase):
    def test_phase3_second_communicate_timeout_does_not_escape(self):
        process=Mock(pid=123)
        process.communicate.side_effect=subprocess.TimeoutExpired('worker',5)
        with patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob'),patch.object(bs.os,'killpg',create=True),patch.object(bs,'_host_group',return_value=None):
            result=rd.compare_url(BASE)
        self.assertFalse(result['comparison_available']);self.assertEqual(result['rows'],[])
        self.assertIn('cleanup could not',str(result['warnings']))
        self.assertEqual(process.communicate.call_count,2)
    def test_second_communicate_timeout_is_caught(self):
        process=Mock(pid=123)
        process.communicate.side_effect=subprocess.TimeoutExpired('worker',5)
        with patch.object(bs.os,'killpg',create=True), patch.object(bs,'WindowsJob') as job:
            self.assertFalse(bs.cleanup_tree(process,job.return_value if os.name=='nt' else None))

    def test_second_timeout_phase3_is_not_false_comparison(self):
        with patch.object(bs,'run_worker',return_value=bs.WorkerResult(reason='execution_deadline',cleanup_confirmed=False)):
            result=rd.compare_url(BASE)
        self.assertFalse(result['comparison_available']);self.assertEqual(result['rows'],[])
        self.assertIn('cleanup could not',str(result['warnings']))

    def test_interruption_always_cleans_tree_and_propagates(self):
        process=Mock();process.communicate.side_effect=KeyboardInterrupt
        with patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob'),patch.object(bs,'cleanup_tree',return_value=True) as cleanup:
            with self.assertRaises(KeyboardInterrupt): bs.run_worker(['worker'],'{}',1)
        cleanup.assert_called_once()

    def test_worker_start_failure_is_unknown(self):
        with patch.object(bs.subprocess,'Popen',side_effect=OSError): result=bs.run_worker(['worker'],'{}',1)
        self.assertEqual(result.reason,'worker_start_failed');self.assertFalse(result.cleanup_confirmed)

    def test_job_assignment_failure_never_releases_stdin_gate(self):
        process=Mock()
        with patch.object(bs.os,'name','nt'),patch.object(bs.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob',side_effect=OSError),patch.object(bs,'cleanup_tree',return_value=True):
            result=bs.run_worker(['worker'],'{}',1)
        process.communicate.assert_not_called();self.assertEqual(result.reason,'worker_setup_or_io_failed')

    def test_windows_assigns_job_before_input_and_closes_on_success(self):
        order=[]; process=Mock(returncode=0)
        process.communicate.side_effect=lambda *a,**k: (order.append('input') or ('ok',None))
        with patch.object(bs.os,'name','nt'),patch.object(bs.subprocess,'CREATE_NEW_PROCESS_GROUP',512,create=True),patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob',side_effect=lambda p: order.append('job') or Mock()) as job,patch.object(bs,'cleanup_tree',return_value=True):
            result=bs.run_worker(['worker'],'{}',1)
        self.assertEqual(order,['job','input']);self.assertEqual(result.output,'ok');self.assertTrue(result.cleanup_confirmed)

    def test_cleanup_failure_does_not_claim_worker_success(self):
        process=Mock(returncode=0);process.communicate.return_value=('ok',None)
        with patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob'),patch.object(bs,'cleanup_tree',return_value=False):
            result=bs.run_worker(['worker'],'{}',1)
        self.assertEqual(result.reason,'cleanup_unconfirmed')

    def test_oversized_result_never_accepted(self):
        process=Mock(returncode=0);process.communicate.return_value=('xxx',None)
        with patch.object(bs.subprocess,'Popen',return_value=process),patch.object(bs,'WindowsJob'),patch.object(bs,'OUTPUT_BYTES',2),patch.object(bs,'cleanup_tree',return_value=True):
            result=bs.run_worker(['worker'],'{}',1)
        self.assertEqual(result.reason,'worker_output_limit')

    def tree(self, mode):
        # Input gate mirrors both production workers. Children intentionally survive
        # normal exit/crash to prove that cleanup is tree-scoped, not root-only.
        script="""import json,subprocess,sys,time,os
from pathlib import Path
r=json.load(sys.stdin)
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=os.name!='nt' and r['mode'].startswith('detached'))
Path(r['path']).write_text(json.dumps([os.getpid(),p.pid]))
time.sleep(0.2)
if r['mode'].endswith('hang'): time.sleep(60)
elif r['mode'].endswith('crash'): os._exit(7)
else: print('ok',flush=True)
"""
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'pids.json';started=time.monotonic()
            result=bs.run_worker([sys.executable,'-c',script],json.dumps(dict(path=str(dest),mode=mode)),1.5 if mode.endswith('hang') else 10)
            self.assertTrue(dest.exists(),'Worker failed to start; no tree check can pass')
            pids=json.loads(dest.read_text())
            self.assertTrue(result.cleanup_confirmed);self.assertFalse(any(pid_running(p) for p in pids))
            self.assertLess(time.monotonic()-started,9)
            return result

    def test_real_timeout_removes_worker_and_descendant(self):
        self.assertEqual(self.tree('hang').reason,'execution_deadline')

    def test_real_crash_removes_descendant(self):
        self.assertEqual(self.tree('crash').reason,'worker_crashed')

    def test_real_success_removes_stray_descendant(self):
        result=self.tree('success');self.assertEqual(result.reason,'');self.assertEqual(result.output.strip(),'ok')

    def test_real_timeout_removes_detached_descendant(self):
        self.assertEqual(self.tree('detached-hang').reason,'execution_deadline')

    def test_real_crash_removes_detached_descendant(self):
        self.assertEqual(self.tree('detached-crash').reason,'worker_crashed')

    def test_real_success_removes_detached_descendant(self):
        self.assertEqual(self.tree('detached-success').reason,'')


class CrawlDeadlineTests(unittest.TestCase):
    def test_valid_json_with_incomplete_worker_schema_is_rejected(self):
        with self.assertRaises(ValueError): common._crawl_from_wire({'pages':[]})
    def worker(self, reason='', cleanup=True, malformed=False):
        def run(command,payload,seconds):
            r=json.loads(payload)
            crawl=common._crawl_site_empty(r['url'],r['limit']);root=page(links=[('/old','Target'),('/old','Target'),('/hang','Hang')])
            target=page('/old',final='/target',chain=[dict(url=BASE+'/old',status=301)])
            root.browser_rendered=target.browser_rendered=True;root.crawl_depth=0;target.crawl_depth=1
            crawl.update(pages=[root,target],browser_used=True,status_checks=[common.status_evidence(root),common.status_evidence(target)])
            crawl['coverage'].update(pages_inspected=2,attempted_urls=3,remaining_queue=[BASE+'/pending'],
                discovered_depths={BASE+'/':0,BASE+'/old':1,BASE+'/hang':1,BASE+'/pending':2},inflight_url=BASE+'/hang',stop_reason='worker_running')
            if not reason: crawl['coverage'].pop('inflight_url');crawl['coverage']['stop_reason']='page_limit'
            if malformed: Path(r['checkpoint']).write_text('invalid')
            else: common._write_crawl_checkpoint(r['checkpoint'],crawl)
            return bs.WorkerResult(output='crawl-complete',reason=reason,cleanup_confirmed=cleanup)
        return run

    def test_deadline_retains_pages_counts_aliases_depth_and_unknown_status(self):
        with patch.object(bs,'run_worker',side_effect=self.worker('execution_deadline')):
            crawl=common.crawl_site(BASE,limit=2,wall_seconds=1)
        self.assertEqual(len(crawl['pages']),2);self.assertEqual(crawl['coverage']['stop_reason'],'execution_deadline')
        self.assertEqual(crawl['coverage']['remaining_queue'],[BASE+'/pending'])
        self.assertEqual(crawl['coverage']['unfinished_url'],BASE+'/hang')
        self.assertIsNone(crawl['status_checks'][-1]['status']);self.assertFalse(crawl['coverage']['observed_graph_complete'])
        links=analyze_links(crawl);target=next(x for x in links['inventory'] if x['URL']==BASE+'/target')
        self.assertEqual(target['Observed link occurrences'],2);self.assertEqual(target['Unique referring pages'],1)
        self.assertEqual(target['Observed seed-relative depth'],1)
        self.assertIn('unknown status',coverage_note(crawl))

    def test_crash_preserves_checkpoint_without_http_or_browser_retry(self):
        with patch.object(bs,'run_worker',side_effect=self.worker('worker_crashed')),patch.object(common,'_crawl_site_local') as retry:
            crawl=common.crawl_site(BASE)
        retry.assert_not_called();self.assertEqual(crawl['coverage']['stop_reason'],'worker_crashed');self.assertEqual(len(crawl['pages']),2)

    def test_missing_checkpoint_is_empty_unverified_not_http_failure(self):
        with patch.object(bs,'run_worker',return_value=bs.WorkerResult(reason='worker_start_failed')):
            crawl=common.crawl_site(BASE)
        self.assertEqual(crawl['pages'],[]);self.assertEqual(crawl['status_checks'],[])
        self.assertEqual(crawl['coverage']['remaining_queue'],[BASE]);self.assertFalse(crawl['coverage']['full_site_complete'])

    def test_invalid_checkpoint_is_not_success(self):
        with patch.object(bs,'run_worker',side_effect=self.worker(malformed=True)):
            crawl=common.crawl_site(BASE)
        self.assertEqual(crawl['coverage']['stop_reason'],'invalid_worker_result');self.assertEqual(crawl['pages'],[])

    def test_normal_success_adds_no_supervision_fields(self):
        with patch.object(bs,'run_worker',side_effect=self.worker()):crawl=common.crawl_site(BASE,limit=2)
        self.assertNotIn('browser_supervision',crawl);self.assertFalse(crawl['browser_error'])
        self.assertEqual(crawl['coverage']['stop_reason'],'page_limit')

    def test_deadline_failure_exports_evidence_and_preserves_nine_files(self):
        with patch.object(bs,'run_worker',side_effect=self.worker('execution_deadline',False)):crawl=common.crawl_site(BASE)
        before=common.overall_scores(crawl['pages'])
        delivery=build_delivery(BASE,crawl=crawl,discovery=discovery());files=delivery_files(delivery)
        self.assertEqual(len(files),9);self.assertEqual(common.overall_scores(crawl['pages']),before)
        self.assertIn('browser_supervision',json.loads(files['evidence.json']))
        self.assertIn(b'Browser execution stopped',files['client-report.html'])
        self.assertIn('cleanup could not',coverage_note(crawl))

    def test_http_only_mode_does_not_start_browser_worker(self):
        with patch.object(bs,'run_worker') as worker,patch.object(common,'crawl_page_requests',return_value=page()):
            crawl=common.crawl_site(BASE,prefer_browser=False)
        worker.assert_not_called();self.assertEqual(len(crawl['pages']),1)

    def test_invalid_limits_never_start_worker(self):
        for kwargs in [dict(limit=501),dict(timeout=float('nan')),dict(timeout=0),dict(wall_seconds=0),dict(wall_seconds=601)]:
            with self.subTest(kwargs=kwargs),patch.object(bs,'run_worker') as worker:
                with self.assertRaises(ValueError):common.crawl_site(BASE,**kwargs)
                worker.assert_not_called()

    def test_checkpoint_budget_preserves_previous_atomic_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'crawl.json';dest.write_bytes(b'previous')
            with patch.object(bs,'OUTPUT_BYTES',2),self.assertRaises(ValueError):
                common._write_crawl_checkpoint(dest,common._crawl_site_empty(BASE,1))
            self.assertEqual(dest.read_bytes(),b'previous')

    def test_context_close_crash_still_closes_browser(self):
        browser=Mock();broker=Mock();broker.prepare_navigation.side_effect=ValueError
        broker.evidence.return_value=dict(partial_render=True,blocked={},resources=[])
        browser.new_context.return_value.close.side_effect=RuntimeError
        with patch('playwright.sync_api.sync_playwright'),patch.object(common,'_launch_browser',return_value=browser),patch('browser_isolation.GetBroker',return_value=broker):
            crawl=common._crawl_site_local(BASE,limit=1)
        browser.close.assert_called_once();self.assertEqual(crawl['coverage']['stop_reason'],'browser_interrupted')


if __name__=='__main__':unittest.main()
