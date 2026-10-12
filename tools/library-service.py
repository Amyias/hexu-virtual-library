"""Small Python stdlib sidecar for npm start; the desktop uses the same book_library module."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from book_library import handle_request


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not handle_request(self):
            self.send_error(404)

    do_POST = do_GET

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()
