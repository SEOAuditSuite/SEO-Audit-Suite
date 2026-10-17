"""Fixed whole-audit container entrypoint. No client-supplied commands or paths."""
import base64
import json
import sys
from contextlib import redirect_stdout


def main():
    try:
        raw=sys.stdin.buffer.read(16385)
        if len(raw)>16384:raise ValueError('Job request too large')
        request=json.loads(raw)
        if set(request)!={'url','pages'} or type(request['pages']) is not int or not 1<=request['pages']<=10:
            raise ValueError('Invalid job')
        from client_workflow import build_delivery,delivery_files
        with redirect_stdout(sys.stderr):
            delivery=build_delivery(request['url'],crawl_limit=request['pages'])
            files=delivery_files(delivery)
        # Existing export bytes/names are not changed. Envelope is deployment-only.
        if sum(len(v) for v in files.values())>5*1024*1024:
            raise ValueError('Output budget exhausted')
        crawl=delivery['audit'].get('crawl',{})
        coverage=crawl.get('coverage') or {}
        partial=bool(crawl.get('errors') or crawl.get('browser_error') or
                     coverage.get('observed_graph_complete') is not True or
                     (crawl.get('browser_security') or {}).get('partial_render'))
        result=dict(status='incomplete' if partial else 'completed',
                    coverage=coverage,files={name:base64.b64encode(value).decode() for name,value in files.items()})
    except Exception:
        result=dict(status='incomplete',http_status=None,
                    reason='Audit unavailable, blocked or resource budget exceeded; no SEO failure inferred',files={})
    sys.stdout.write(json.dumps(result,separators=(',',':'))+'\n')
    sys.stdout.flush()


if __name__=='__main__':main()
