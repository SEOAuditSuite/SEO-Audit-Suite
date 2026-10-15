"""C3A local binding and browser-worker environment policy regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import browser_supervision as bs


class LocalLaunchTests(unittest.TestCase):
    def test_both_batch_python_branches_bind_only_ipv4_loopback(self):
        commands=[line.strip() for line in (ROOT/'START-APP.bat').read_text().splitlines() if '-m streamlit run app.py' in line]
        self.assertEqual(len(commands),2)
        for command in commands:
            self.assertEqual(command.count('--server.address=127.0.0.1'),1)
            self.assertNotIn('0.0.0.0',command);self.assertNotIn('%*',command)
        self.assertTrue(commands[0].startswith('".venv\\Scripts\\python.exe"'))
        self.assertTrue(commands[1].startswith('python '))

    def test_launcher_does_not_disable_cors_or_xsrf(self):
        text=((ROOT/'START-APP.bat').read_text()+(ROOT/'.streamlit/config.toml').read_text()).lower()
        for key in ('enablecors','enablexsrfprotection'):
            self.assertNotIn(key+'=false',text.replace(' ',''))
        self.assertNotIn('streamlit_server_enablecors=false',text)
        self.assertNotIn('streamlit_server_enablexsrfprotection=false',text)


class EnvironmentTests(unittest.TestCase):
    def test_explicit_allowlist_drops_credentials_proxy_and_unrelated_values(self):
        source={name:'synthetic-canary' for name in ('PAGESPEED_API_KEY','OPENAI_API_KEY','AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY','AZURE_CLIENT_SECRET','GITHUB_TOKEN','PASSWORD','CLIENT_NAME',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','NODE_OPTIONS','NODE_PATH',
            'PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','PYTHONINSPECT','PYTHONUSERBASE','SSLKEYLOGFILE')}
        env=bs._worker_environment(source)
        self.assertTrue(set(source).isdisjoint(env));self.assertNotIn('synthetic-canary',str(env))

    def test_windows_python_and_chrome_discovery_paths_survive(self):
        source={'Path':'C:\\Windows\\System32','SystemRoot':'C:\\Windows','WINDIR':'C:\\Windows',
            'COMSPEC':'C:\\Windows\\System32\\cmd.exe','USERPROFILE':'C:\\Audit',
            'LOCALAPPDATA':'C:\\Audit\\Local','APPDATA':'C:\\Audit\\Roaming',
            'ProgramFiles':'C:\\Program Files','ProgramFiles(x86)':'C:\\Program Files (x86)',
            'PROGRAMW6432':'C:\\Program Files','TEMP':'C:\\AuditTemp','TMP':'C:\\AuditTemp'}
        env=bs._worker_environment(source)
        for key,value in source.items():self.assertEqual(env[key],value)

    def test_posix_and_explicit_playwright_bootstrap_paths_survive(self):
        source={key:'/synthetic/path' for key in ('PATH','HOME','TMPDIR','XDG_RUNTIME_DIR','XDG_CACHE_HOME',
            'DISPLAY','WAYLAND_DISPLAY','PLAYWRIGHT_BROWSERS_PATH','PLAYWRIGHT_NODEJS_PATH')}
        env=bs._worker_environment(source)
        for key,value in source.items():self.assertEqual(env[key],value)

    def test_python_runtime_settings_are_fixed_not_inherited(self):
        env=bs._worker_environment(dict(PYTHONUTF8='0',PYTHONIOENCODING='ascii',PYTHONNOUSERSITE='0',PYTHONDONTWRITEBYTECODE='0'))
        self.assertEqual(env,dict(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1'))

    def test_parent_environment_and_pagespeed_key_are_not_mutated(self):
        with patch.dict(os.environ,{'PAGESPEED_API_KEY':'synthetic-parent-key','C3A_TEST_SECRET':'synthetic-secret'}):
            before=dict(os.environ);bs._worker_environment()
            self.assertEqual(dict(os.environ),before)

    def test_supervisor_passes_only_sanitized_environment_and_retains_deadline(self):
        process=Mock(returncode=0);process.communicate.return_value=('ok',None)
        with patch.dict(os.environ,{'PAGESPEED_API_KEY':'synthetic-parent-key'}),patch.object(bs.subprocess,'Popen',return_value=process) as launch,patch.object(bs,'WindowsJob'),patch.object(bs,'_host_group',return_value=None),patch.object(bs,'cleanup_tree',return_value=True):
            result=bs.run_worker(['worker'],'{}',10)
        self.assertEqual(result.output,'ok');self.assertTrue(result.cleanup_confirmed)
        self.assertNotIn('PAGESPEED_API_KEY',launch.call_args.kwargs['env'])
        self.assertLessEqual(process.communicate.call_args.kwargs['timeout'],10)

    def test_real_worker_uses_same_python_and_venv_without_parent_import_hooks(self):
        code="""import json,os,sys
json.load(sys.stdin)
print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,no_user_site=sys.flags.no_user_site,
secret_present=any(k in os.environ for k in ['PAGESPEED_API_KEY','C3A_TEST_SECRET','PYTHONPATH','PYTHONHOME','NODE_OPTIONS']))))
"""
        # Python import hooks are only installed after this parent has started.
        with patch.dict(os.environ,{'PAGESPEED_API_KEY':'synthetic-parent-key','C3A_TEST_SECRET':'synthetic-secret',
                                   'PYTHONPATH':'/nonexistent/c3a-import-hook','PYTHONHOME':'/nonexistent/c3a-home','NODE_OPTIONS':'--invalid-c3a-option'}):
            result=bs.run_worker([sys.executable,'-c',code],'{}',10)
            self.assertEqual(os.environ['PAGESPEED_API_KEY'],'synthetic-parent-key')
        self.assertEqual(result.reason,'');self.assertTrue(result.cleanup_confirmed)
        data=json.loads(result.output);self.assertFalse(data['secret_present']);self.assertEqual(data['no_user_site'],1)
        self.assertEqual(Path(data['executable']),Path(sys.executable));self.assertEqual(data['prefix'],sys.prefix)

    def test_real_worker_imports_project_and_required_installed_dependencies(self):
        code="""import json,sys
json.load(sys.stdin)
sys.path.insert(0,sys.argv[1])
import common,safe_http,browser_isolation,rendering_diagnostics,playwright.sync_api
print('imports-ok')
"""
        result=bs.run_worker([sys.executable,'-c',code,str(ROOT)],'{}',10)
        self.assertEqual(result.reason,'');self.assertTrue(result.cleanup_confirmed)
        self.assertEqual(result.output.strip(),'imports-ok')

    def test_parent_pagespeed_screen_retains_environment_key_and_request(self):
        from streamlit.testing.v1 import AppTest
        response=Mock(ok=True);response.json.return_value={}
        with patch.dict(os.environ,{'PAGESPEED_API_KEY':'synthetic-parent-key'}):
            app=AppTest.from_file(str(ROOT/'pages/3_PageSpeed.py'),default_timeout=20).run()
            self.assertEqual(app.text_input[1].value,'synthetic-parent-key')
            app.text_input[0].set_value('https://example.test/')
            with patch('requests.get',return_value=response) as request:app.button[0].click().run()
            self.assertFalse(app.exception);self.assertEqual(request.call_args.kwargs['params']['key'],'synthetic-parent-key')
            self.assertEqual(os.environ['PAGESPEED_API_KEY'],'synthetic-parent-key')

    def test_missing_worker_executable_stays_unavailable_without_retry(self):
        with patch.object(bs.subprocess,'Popen',side_effect=OSError) as launch:
            result=bs.run_worker(['missing-worker'],'{}',1)
        self.assertEqual(result.reason,'worker_start_failed');launch.assert_called_once()


if __name__=='__main__':unittest.main()
