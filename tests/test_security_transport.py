"""C1 controlled tests. Loopback permission exists only in test mocks, never UI/config."""
import gzip
import os
from pathlib import Path
import socket
import ssl
import threading
import time
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import safe_http as sh
from common import fetch, check_urls, crawl_site
from test_http_link_integration import ControlledSite

BASE = 'https://audit.example.test'
PUBLIC = '93.184.216.34'


def answer(ip=PUBLIC, port=443):
    family = socket.AF_INET6 if ':' in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, '', (ip, port))


class AddressTests(unittest.TestCase):
    def test_all_nonpublic_and_transition_addresses_rejected_before_socket(self):
        for ip in ('127.0.0.1','10.0.0.1','172.16.1.1','192.168.1.1','169.254.169.254',
                   '100.64.0.1','0.0.0.0','224.0.0.1','240.0.0.1','192.0.2.1','192.0.0.8',
                   '::','::1','fc00::1','fe80::1','ff02::1','2001:db8::1','::ffff:127.0.0.1',
                   '64:ff9b::7f00:1','2002:7f00:1::'):
            with self.subTest(ip=ip), patch.object(sh.socket,'getaddrinfo',return_value=[answer(ip)]), patch.object(sh.socket,'socket') as connect:
                with self.assertRaises(sh.TransportError): sh.SafeSession().get(BASE)
                connect.assert_not_called()

    def test_mixed_answers_fail_closed_in_either_order(self):
        for rows in ([answer(),answer('::1')],[answer('127.0.0.1'),answer()]):
            with patch.object(sh.socket,'getaddrinfo',return_value=rows), patch.object(sh.socket,'socket') as connect:
                with self.assertRaises(sh.TransportError): sh.SafeSession().get(BASE)
                connect.assert_not_called()

    def test_legacy_encodings_credentials_and_schemes_rejected_before_dns(self):
        for url in ('http://2130706433','http://127.1','http://0177.0.0.1','http://0x7f000001',
                    'http://user:secret@audit.example.test','file:///etc/passwd','ftp://example.com',
                    'http://[fe80::1%25eth0]/','http://audit.example.test\\@127.0.0.1',
                    'http://audit.example.test:0','http://audit.example.test\n/',
                    'http://１２７.０.０.１/'):
            with self.subTest(url=url), patch.object(sh.socket,'getaddrinfo') as dns:
                with self.assertRaises(sh.TransportError): sh.SafeSession().get(url)
                dns.assert_not_called()

    def test_ipv6_approved_numeric_address_and_port_preserved(self):
        with patch.object(sh.socket,'getaddrinfo',return_value=[answer('2606:4700:4700::1111',9999)]):
            self.assertEqual(sh.resolve_addresses('audit.example.test',443,time.monotonic()+1),
                             [(socket.AF_INET6,('2606:4700:4700::1111',443,0,0))])

    def test_no_dns_for_public_literal(self):
        with patch.object(sh.socket,'getaddrinfo') as dns:
            sh.resolve_addresses(PUBLIC,80,time.monotonic()+1)
            dns.assert_not_called()

    def test_dns_timeout_is_bounded_and_capacity_recovers(self):
        release=threading.Event()
        def stalled(*args,**kwargs):release.wait(2);return [answer()]
        try:
            with patch.object(sh.socket,'getaddrinfo',side_effect=stalled):
                start=time.monotonic()
                with self.assertRaises(sh.TransportError):sh.resolve_addresses('audit.example.test',80,start+.05)
                self.assertLess(time.monotonic()-start,1)
        finally:release.set()

    def test_dns_failure_and_empty_answers(self):
        for rows in ([],[answer('fe80::1%1')]):
            with patch.object(sh.socket,'getaddrinfo',return_value=rows):
                with self.assertRaises(sh.TransportError):sh.resolve_addresses('audit.example.test',80,time.monotonic()+1)


class BoundConnectionTests(unittest.TestCase):
    def transport(self,url=BASE+'/a%2Fb/?X=1&X=2&key=%2f'):
        wire=Mock(status=200,reason='OK',length=0)
        wire.isclosed.return_value=False
        wire.getheaders.return_value=[('Content-Type','text/html; charset=utf-8')]
        wire.read1.side_effect=[b'hello',b'']
        conn=Mock();conn.getresponse.return_value=wire
        return conn,wire

    def test_rebinding_never_resolves_twice_and_tls_uses_original_name(self):
        conn,wire=self.transport();context=Mock();raw=Mock();tls=Mock();context.wrap_socket.return_value=tls
        with patch.object(sh.socket,'getaddrinfo',side_effect=[[answer()],[answer('127.0.0.1')]]) as dns, patch.object(sh.socket,'socket',return_value=raw), patch.object(sh.ssl,'create_default_context',return_value=context), patch.object(sh,'_DeadlineConnection',return_value=conn):
            r=sh.SafeSession().get(BASE+'/a%2Fb/?X=1&X=2&key=%2f',headers={'Authorization':'secret','Cookie':'secret','Host':'evil','User-Agent':'test'})
        self.assertEqual(dns.call_count,1);raw.connect.assert_called_once_with((PUBLIC,443))
        context.wrap_socket.assert_called_once_with(raw,server_hostname='audit.example.test',do_handshake_on_connect=False)
        tls.do_handshake.assert_called_once()
        args=conn.request.call_args;self.assertEqual(args.args,('GET','/a%2Fb/?X=1&X=2&key=%2f'))
        headers=args.kwargs['headers'];self.assertEqual(headers['Host'],'audit.example.test')
        self.assertNotIn('Authorization',headers);self.assertNotIn('Cookie',headers)
        self.assertEqual(r.content,b'hello');self.assertEqual(r.url,BASE+'/a%2Fb/?X=1&X=2&key=%2f')
        conn.close.assert_called_once();tls.close.assert_called()

    def test_connect_fallback_uses_only_approved_addresses(self):
        conn,_=self.transport();a,b=Mock(),Mock();a.connect.side_effect=OSError()
        with patch.object(sh.socket,'getaddrinfo',return_value=[answer(),answer('1.1.1.1')]) as dns, patch.object(sh.socket,'socket',side_effect=[a,b]),patch.object(sh,'_DeadlineConnection',return_value=conn):
            sh.SafeSession().get('http://audit.example.test/')
        self.assertEqual(dns.call_count,1);b.connect.assert_called_once_with(('1.1.1.1',80))

    def test_ipv6_literal_connection_and_host_header(self):
        conn,_=self.transport();sock=Mock()
        with patch.object(sh.socket,'getaddrinfo') as dns,patch.object(sh.socket,'socket',return_value=sock) as factory,patch.object(sh,'_DeadlineConnection',return_value=conn):
            sh.SafeSession().get('http://[2606:4700:4700::1111]:8080/a?x=1#fragment')
        dns.assert_not_called();factory.assert_called_once_with(socket.AF_INET6,socket.SOCK_STREAM)
        sock.connect.assert_called_once_with(('2606:4700:4700::1111',8080,0,0))
        self.assertEqual(conn.request.call_args.args,('GET','/a?x=1'))
        self.assertEqual(conn.request.call_args.kwargs['headers']['Host'],'[2606:4700:4700::1111]:8080')

    def test_idna_authority_keeps_resource_identity(self):
        scheme,host,port,authority,target=sh._target('https://bücher.example:443/Case/%2f/?q=%2F&q=2')
        self.assertEqual((host,authority),('xn--bcher-kva.example','xn--bcher-kva.example:443'))
        self.assertEqual(target,'/Case/%2f/?q=%2F&q=2')

    def test_implicit_reconnect_forbidden(self):
        with self.assertRaises(sh.TransportError):sh._DeadlineConnection('audit.example.test').connect()

    def test_proxy_netrc_and_cookie_inheritance_disabled(self):
        conn,_=self.transport()
        with patch.dict(os.environ,{'HTTPS_PROXY':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1','NETRC':'/nonexistent'}),patch.object(sh.socket,'getaddrinfo',return_value=[answer()]) as dns,patch.object(sh.socket,'socket'),patch.object(sh,'_DeadlineConnection',return_value=conn):
            with sh.SafeSession() as s:
                self.assertFalse(s.trust_env);s.get('http://audit.example.test/')
            self.assertEqual(dns.call_args.args[:2],('audit.example.test',80))

    def test_deadline_rejects_before_connection(self):
        with patch.object(sh.socket,'socket') as connect:
            with self.assertRaises(sh.TransportError):sh.SafeSession().get('http://'+PUBLIC,deadline=time.monotonic()-1)
            connect.assert_not_called()

    def test_invalid_budgets(self):
        for kw in ({'timeout':0},{'timeout':float('nan')},{'max_bytes':0},{'allow_redirects':True}):
            with self.subTest(kw=kw),self.assertRaises(sh.TransportError):sh.SafeSession().get(BASE,**kw)


class WireHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.server.seen.append((self.path,dict(self.headers)))
        if self.path=='/slow-header':
            self.wfile.write(b'HTTP/1.1 200 OK\r\nX: ');self.wfile.flush();time.sleep(.4);return
        data=gzip.compress(b'x'*10000) if self.path.startswith('/gzip') else b'hello'
        self.send_response(200)
        if self.path.startswith('/gzip'):self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Length',str(len(data)+(3 if self.path=='/short' else 0)))
        self.end_headers()
        try:
            if self.path=='/slow-body':time.sleep(.4)
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass


class WireTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),WireHandler);self.server.seen=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://audit.example.test:{self.server.server_port}'
        self.dns=patch.object(sh.socket,'getaddrinfo',return_value=[answer('127.0.0.1',self.server.server_port)])
        self.policy=patch.object(sh,'_public_address',return_value=True)
        self.dns.start();self.policy.start()
    def tearDown(self):
        self.dns.stop();self.policy.stop();self.server.shutdown();self.server.server_close();self.thread.join()
    def test_real_http_path_query_host_and_bytes(self):
        url=self.base+'/a%2fb/?x=1&x=2&v=%2F';r=sh.SafeSession().get(url)
        self.assertEqual(r.content,b'hello');self.assertEqual(r.url,url)
        path,headers=self.server.seen[-1];self.assertEqual(path,'/a%2fb/?x=1&x=2&v=%2F')
        self.assertEqual(headers['Host'],self.base.split('//')[1]);self.assertNotIn('Authorization',headers)
    def test_gzip_success_and_bomb_limit(self):
        self.assertEqual(sh.SafeSession().get(self.base+'/gzip').content,b'x'*10000)
        with self.assertRaises(sh.TransportError):sh.SafeSession().get(self.base+'/gzip-bomb',max_bytes=1000)
    def test_plain_size_limit(self):
        with self.assertRaises(sh.TransportError):sh.SafeSession().get(self.base+'/',max_bytes=4)
    def test_truncated_response_not_success(self):
        with self.assertRaises(sh.TransportError):sh.SafeSession().get(self.base+'/short')
    def test_session_budget_consumes_successful_and_failed_bodies(self):
        session=sh.SafeSession(max_total_bytes=6)
        self.assertEqual(session.get(self.base+'/').content,b'hello')
        with self.assertRaises(sh.TransportError):session.get(self.base+'/')
        self.assertGreaterEqual(session.decoded_bytes,6)
        before=len(self.server.seen)
        with self.assertRaises(sh.TransportError):session.get(self.base+'/')
        self.assertEqual(len(self.server.seen),before)

    def test_header_and_body_total_deadlines(self):
        for path in ('/slow-header','/slow-body'):
            start=time.monotonic()
            with self.assertRaises(sh.TransportError):sh.SafeSession().get(self.base+path,timeout=2,deadline=start+.08)
            self.assertLess(time.monotonic()-start,.8)
    def test_real_tls_hostname_sni_and_wrong_certificate_rejection(self):
        self.server.shutdown();self.thread.join()
        fixtures=Path(__file__).with_name('fixtures');context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(fixtures/'test-only-tls.crt'),str(fixtures/'test-only-tls.key'))
        seen=[];context.set_servername_callback(lambda sock,name,ctx:seen.append(name))
        self.server.socket=context.wrap_socket(self.server.socket,server_side=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        trusted=ssl.create_default_context(cafile=str(fixtures/'test-only-tls.crt'))
        self.assertTrue(trusted.check_hostname);self.assertEqual(trusted.verify_mode,ssl.CERT_REQUIRED)
        with patch.object(sh.ssl,'create_default_context',return_value=trusted):
            r=sh.SafeSession().get(self.base.replace('http:','https:')+'/')
            self.assertEqual(r.content,b'hello');self.assertIn('audit.example.test',seen)
            with self.assertRaises(sh.TransportError):sh.SafeSession().get(self.base.replace('http:','https:').replace('audit.example.test','wrong.example.test')+'/')
        self.assertEqual(len(self.server.seen),1)
        with self.assertRaises(sh.TransportError):
            sh.SafeSession().get(self.base.replace('http:','https:')+'/')
        self.assertEqual(len(self.server.seen),1)


class EvidenceTests(unittest.TestCase):
    def test_private_dns_is_unknown_not_broken(self):
        with patch.object(sh.socket,'getaddrinfo',return_value=[answer('127.0.0.1')]),patch.object(sh.socket,'socket') as connect:
            row=check_urls([BASE])[0];crawl=crawl_site(BASE,prefer_browser=False,limit=1)
        self.assertIsNone(row['status']);self.assertNotEqual(row['classification'],'broken')
        self.assertEqual(crawl['pages'],[]);self.assertFalse(crawl['coverage']['full_site_complete']);connect.assert_not_called()
    def test_each_redirect_resolves_again_and_rebinding_hop_is_blocked(self):
        from test_http_link_integration import FixtureHandler
        with ControlledSite() as site:
            original=sh.resolve_addresses;calls=[]
            def resolve(host,port,deadline):
                calls.append(host)
                if len(calls)==2:raise sh.TransportError('Non-public DNS destination blocked')
                return original(host,port,deadline)
            with patch.object(sh,'resolve_addresses',side_effect=resolve):
                with self.assertRaises(sh.TransportError):fetch(site.base+'/old')
            self.assertEqual(len(calls),2);self.assertEqual(len(site.server.observed_requests),1)


if __name__=='__main__':unittest.main()
