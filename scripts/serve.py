"""Önbelleksiz yerel sunucu: web/ ve data/ değişince tarayıcı her zaman en son dosyayı alır.

Büyük GeoJSON dosyaları gzip ile sıkıştırılarak gönderilir (bir ilçe ~13 MB yerine ~3 MB); sıkıştırılmış
hâli dosya değişene kadar bellekte tutulur.

Çalıştırma:  python3 scripts/serve.py            ->  http://localhost:8765/web/
             python3 scripts/serve.py --lan      ->  aynı ağdaki tablet ya da ikinci bilgisayar da açabilir
"""
import argparse
import gzip
import http.server
import os
import socket
from functools import partial
from pathlib import Path

PORT = int(os.environ.get("PORT", "8765"))
ROOT = Path(__file__).resolve().parents[1]
COMPRESS = {".json", ".geojson", ".js", ".css", ".html", ".csv", ".svg"}
_cache: dict[str, tuple[float, bytes]] = {}


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".geojson": "application/geo+json", ".js": "text/javascript", ".woff2": "font/woff2"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if (path.suffix in COMPRESS and path.is_file()
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            mtime = path.stat().st_mtime
            hit = _cache.get(str(path))
            if not hit or hit[0] != mtime:
                hit = (mtime, gzip.compress(path.read_bytes(), compresslevel=6))
                _cache[str(path)] = hit
            body = hit[1]
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return _Bytes(body)
        return super().send_head()


class _Bytes:
    """send_head'in döndürdüğü dosya benzeri nesne."""

    def __init__(self, data: bytes):
        self.data = data

    def read(self, *_):
        d, self.data = self.data, b""
        return d

    def close(self):
        pass


def main():
    ap = argparse.ArgumentParser(description="Sanal Baraj yerel sunucusu")
    ap.add_argument("--lan", action="store_true", help="yerel ağdaki diğer cihazlara da aç (yalnız güvendiğiniz ağda)")
    args = ap.parse_args()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    handler = partial(Handler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer((host, PORT), handler) as httpd:
        print(f"http://localhost:{PORT}/web/")
        if args.lan:
            try:
                ip = socket.gethostbyname(socket.gethostname())
                print(f"Ağdaki cihazlardan: http://{ip}:{PORT}/web/")
            except OSError:
                pass
        httpd.serve_forever()


if __name__ == "__main__":
    main()
