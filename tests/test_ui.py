import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from client_workflow import build_delivery
from test_regressions import fixture_page, discovery


class UITests(unittest.TestCase):
    def test_every_tool_is_registered_and_opens_from_main_app(self):
        from navigation import PAGE_GROUPS
        registered = [path for entries in PAGE_GROUPS.values() for path, _ in entries]
        tools = {str(path.relative_to(ROOT)).replace('\\', '/') for path in (ROOT/'pages').glob('*.py')}
        self.assertEqual(tools, set(registered) - {'overview.py'})
        self.assertEqual(len(registered), len(set(registered)))
        app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=20).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.sidebar.caption)
        for path in registered:
            with self.subTest(page=path):
                app.switch_page(path).run()
                self.assertFalse(app.exception)

    def test_client_workspace_retains_saved_run(self):
        delivery = build_delivery('https://example.test', crawl={'pages':[fixture_page()], 'errors':[], 'browser_used':False}, discovery=discovery())
        app = AppTest.from_file(str(ROOT/'pages/23_Client_Workspace.py'), default_timeout=20).run()
        self.assertFalse(app.exception)
        app.text_input[0].set_value('https://example.test')
        with patch('client_workflow.build_delivery', return_value=delivery):
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['client_delivery']['model']['website'], 'https://example.test')
        archive = app.session_state['client_zip']
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['client_zip'], archive)

    def test_changed_pages_initialize(self):
        for name in ['app.py','pages/13_GEO_Intelligence.py','pages/15_AI_Crawler_Accessibility.py','pages/22_Client_Report_PDF.py']:
            with self.subTest(page=name):
                app = AppTest.from_file(str(ROOT/name), default_timeout=20).run()
                self.assertFalse(app.exception)

if __name__ == '__main__':
    unittest.main()
