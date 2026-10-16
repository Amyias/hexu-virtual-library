"""Development sidecar: reuse the desktop's exact settings, chat and book handlers.
Importing the service does not initialise ASR or start the updater/window.
"""
import importlib.util
import json
from http.server import ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("hexu_server", Path(__file__).with_name("asr-server.py"))
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class Handler(server_module.Handler):
    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_port}), flush=True)
    server.serve_forever()
