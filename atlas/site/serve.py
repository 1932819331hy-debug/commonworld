#!/usr/bin/env python3
"""Local preview server for the built Atlas (stdlib only). Mimics Cloudflare Pages:
clean directory URLs, /atlas/x -> 301 /atlas/x/, real 404 status with /404.html, / serves the Commonworld landing (dist/index.html).

    python3 atlas/site/serve.py            # http://localhost:8080/atlas/
    python3 atlas/site/serve.py 9000       # another port
"""
import http.server, os, sys

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist')


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIST, **k)

    def send_head(self):
        path = self.path.split('?', 1)[0].split('#', 1)[0]
        fs = self.translate_path(path)
        if os.path.isdir(fs) and not path.endswith('/'):
            q = self.path[len(path):]
            return self._redirect(path + '/' + q, 301)
        if os.path.isdir(fs):
            fs = os.path.join(fs, 'index.html')
        if not os.path.isfile(fs):
            body = open(os.path.join(DIST, '404.html'), 'rb').read()
            self.send_response(404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body) if self.command != 'HEAD' else None
            return None
        return super().send_head()

    def _redirect(self, loc, code):
        self.send_response(code)
        self.send_header('Location', loc)
        self.send_header('Content-Length', '0')
        self.end_headers()
        return None

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    if not os.path.isdir(DIST):
        sys.exit('dist/ not found: run  python3 atlas/site/build.py  first')
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    http.server.SimpleHTTPRequestHandler.extensions_map.update({'.js': 'text/javascript', '.json': 'application/json', '.xml': 'application/xml'})
    print(f'Preview: http://localhost:{port}/ (landing)  http://localhost:{port}/atlas/ (Atlas)   (Ctrl+C to stop)')
    http.server.ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
