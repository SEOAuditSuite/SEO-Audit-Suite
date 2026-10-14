"""Missing/terminated Chrome checks must retain flushed progress and no fake passes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).with_name('browser_c2a_validation.py')


def harness():
    spec=importlib.util.spec_from_file_location('c2a_diagnostic_fixture',SCRIPT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class HarnessDiagnosticsTests(unittest.TestCase):
    def test_failed_launch_keeps_stage_and_zero_executed_results(self):
        h=harness()
        with tempfile.TemporaryDirectory() as tmp,patch('playwright.sync_api.sync_playwright'),patch.object(h.bi,'launch_browser',side_effect=RuntimeError('synthetic unavailable')),patch.object(h.faulthandler,'dump_traceback_later') as dump,patch.object(h.faulthandler,'cancel_dump_traceback_later') as cancel,contextlib.redirect_stdout(io.StringIO()) as logs,contextlib.redirect_stderr(io.StringIO()):
            out=Path(tmp);self.assertEqual(h.main(out),1)
            result=json.loads((out/'browser-results.json').read_text());progress=json.loads((out/'progress.json').read_text())
            self.assertEqual(result['status'],'blocked');self.assertEqual(result['executed_checks'],0);self.assertEqual(result['passed_checks'],0)
            self.assertEqual(progress['status'],'blocked');self.assertTrue(progress['history'])
            self.assertIn('secure browser probe starting',logs.getvalue())
            self.assertEqual(dump.call_args.args[0],30);self.assertTrue(dump.call_args.kwargs['repeat']);cancel.assert_called_once()
    def test_stalled_launch_leaves_flushed_progress_before_outer_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            code="""import importlib.util,time
from unittest.mock import patch
from pathlib import Path
spec=importlib.util.spec_from_file_location('stalled_c2a',SCRIPT)
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
h.bi.launch_browser=lambda p: time.sleep(60)
with patch('playwright.sync_api.sync_playwright'):h.main(Path(OUTPUT))
""".replace('SCRIPT',repr(str(SCRIPT.resolve()))).replace('OUTPUT',repr(tmp))
            p=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):p.communicate(timeout=5)
            finally:
                p.kill();stdout,stderr=p.communicate(timeout=5)
            progress=json.loads((Path(tmp)/'progress.json').read_text())
            self.assertEqual(progress['status'],'running');self.assertEqual(progress['executed_checks'],0)
            self.assertIn('secure browser probe starting',stdout)
            self.assertFalse((Path(tmp)/'browser-results.json').exists())


if __name__=='__main__':unittest.main()
