import importlib.util
import json
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import updater

spec = importlib.util.spec_from_file_location('library_server', Path(__file__).resolve().parents[1] / 'tools/asr-server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class AutomaticUpdateTests(unittest.TestCase):
    def run_startup(self, available=True):
        listener = Mock(server_address=('127.0.0.1', 8090))
        result = {'state': 'update-available' if available else 'up-to-date', 'can_apply': available}
        with patch.object(server, 'attach_console'), patch.object(server, 'running_instance', return_value=None), \
             patch.object(server, 'Server', return_value=listener), patch.object(server, 'warm_model'), \
             patch.object(server, 'model_state', return_value=(False, {})), \
             patch.object(server, 'llm_state', return_value=(None, None, {'model': 'test'})), \
             patch.object(server, 'install_root', return_value=Path('test-install')), \
             patch.object(server, 'update_token', return_value=''), patch.object(server, 'window_mode', return_value=False), \
             patch.object(server, 'note') as note, \
             patch.object(server._stop, 'wait', side_effect=lambda seconds=None: seconds != 1.5), \
             patch('builtins.print'), \
             patch.object(server.time, 'sleep'), patch.object(server.threading, 'Thread', ImmediateThread), \
             patch.object(updater, 'status', return_value=result), \
             patch.object(updater, 'begin', return_value=(True, 'started')) as begin, \
             patch.object(sys, 'argv', ['library', '--no-browser']):
            server.main()
            return begin.call_count, note.call_count

    def test_startup_installs_detected_release_without_button_click(self):
        self.assertEqual(self.run_startup()[0], 1)

    def test_normal_startup_does_not_wait_for_address_dialog(self):
        self.assertEqual(self.run_startup(False)[1], 0)

    def test_current_release_does_not_start_an_update(self):
        self.assertEqual(self.run_startup(False)[0], 0)

    def test_watcher_retries_failed_check_then_automatically_applies(self):
        with patch.object(server, 'install_root', return_value=Path('install')), \
             patch.object(server._stop, 'wait', side_effect=[False, False, True]), \
             patch.object(server._stop, 'is_set', return_value=False), \
             patch.object(server, 'update_token', return_value=''), patch.object(updater, 'busy', return_value=False), \
             patch.object(updater, 'status', side_effect=[OSError('offline'), {'can_apply': True}]), \
             patch.object(updater, 'begin', return_value=(True, 'started')) as begin:
            server.automatic_updates(interval=1)
            self.assertEqual(begin.call_count, 1)

    def test_duplicate_update_is_rejected_while_checking(self):
        with patch.dict(updater._progress, state='checking'), patch.object(updater, 'status') as status:
            ok, _ = updater.begin(Path('site'), Path('install'), '', 0, lambda: None)
            self.assertFalse(ok)
            status.assert_not_called()

    def test_unsigned_asset_never_downloads_or_installs(self):
        with patch.object(updater, '_fetch_to') as fetch:
            self.assertFalse(updater._download({'size': 50}, Path('not-created.zip'), '', 'program'))
            fetch.assert_not_called()

    def test_missing_model_does_not_start_incomplete_update(self):
        with patch.object(updater, 'installed', return_value={'version': '1.0.0'}), \
             patch.object(updater, 'has_model', return_value=False), \
             patch.object(updater, '_api', return_value={'tag_name': 'v2.0.0', 'assets': [{'name': 'v2-program.zip'}]}), \
             patch.object(updater, '_model_asset', return_value=None):
            result = updater._inspect(Path('site'), Path('install'), object())
            self.assertFalse(result['can_apply'])
            self.assertEqual(result['state'], 'error')

    def test_source_checkout_never_starts_automatic_install(self):
        with patch.object(server, 'install_root', return_value=None), patch.object(updater, 'status') as status:
            server.automatic_updates()
            status.assert_not_called()

    def test_invalid_zip_never_closes_working_application(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'program.zip'
            target.write_bytes(b'not a zip archive')
            payload = {'program_asset': {'name': target.name}, 'latest': {'version': '2.0.0'}}
            with patch.object(updater, 'work_dir', return_value=Path(directory)), \
                 patch.object(updater, '_download', return_value=True), \
                 patch.object(updater.subprocess, 'Popen') as launch:
                ready = Mock()
                updater._apply_inner(payload, Path('install'), '', 0, ready)
                ready.assert_not_called()
                launch.assert_not_called()
                self.assertEqual(updater.progress()['state'], 'failed')

    def test_headless_restart_does_not_open_a_window(self):
        with patch.object(server, 'frozen', return_value=True):
            self.assertFalse(server.window_mode(server.parse_argv(['--no-browser'])))

    @unittest.skipUnless(os.name == 'nt', 'Windows helper')
    def test_real_helper_replaces_install_restarts_and_removes_old_copy(self):
        compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():
            self.skipTest('C# fixture compiler unavailable')
        cache = Path(__file__).resolve().parents[1] / '.cache'
        cache.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='update-test-', dir=cache) as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(root.parent, cache.resolve())
            install = root / 'installed'
            (install / '_internal/models/sense-voice').mkdir(parents=True)
            model = install / updater.MODEL_RELATIVE
            model.write_bytes(b'unchanged-model-fixture')
            original_hash = hashlib.sha256(model.read_bytes()).hexdigest()
            source = root / 'fixture.cs'
            source.write_text('''using System;using System.IO;using System.Net;using System.Net.Sockets;using System.Text;
class App { static void Main(string[] args) {int port=0;for(int i=0;i<args.Length-1;i++)if(args[i]=="--port")port=int.Parse(args[i+1]);
var listener=new TcpListener(IPAddress.Loopback,port);listener.Start();File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"fixture.pid"),System.Diagnostics.Process.GetCurrentProcess().Id.ToString());while(true){using(var c=listener.AcceptTcpClient()){var s=c.GetStream();var input=new byte[8192];s.Read(input,0,input.Length);var data=File.ReadAllBytes(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"_internal/build-info.json"));var head=Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\\r\\nContent-Type: application/json\\r\\nContent-Length: "+data.Length+"\\r\\nConnection: close\\r\\n\\r\\n");s.Write(head,0,head.Length);s.Write(data,0,data.Length);}}}}
''', encoding='utf-8')
            exe = install / 'fixture.exe'
            subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(exe), str(source)], check=True, capture_output=True)
            (install / '_internal/build-info.json').write_text(json.dumps({'version': '1.0.0', 'commit': 'old'}))
            (install / 'obsolete.txt').write_text('must disappear')
            work = root / 'work'; work.mkdir()
            archive = work / 'program.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.write(exe, 'fixture.exe')
                z.writestr('_internal/build-info.json', json.dumps({'version': '2.0.0', 'commit': 'new'}))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(exe)):
                helper = updater._write_helper(work, install, archive, None, 2147483000, ('--port', str(port), '--no-browser'), '2.0.0')
            restarted_pid = None
            try:
                result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper)], capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                record = json.loads((work / 'result.json').read_text(encoding='utf-8-sig'))
                restarted_pid = record['pid']
                self.assertEqual(record['state'], 'completed')
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/build-info.json') as response:
                    self.assertEqual(json.load(response)['version'], '2.0.0')
                self.assertEqual(hashlib.sha256(model.read_bytes()).hexdigest(), original_hash)
                self.assertFalse((install / 'obsolete.txt').exists())
                self.assertFalse(list(root.glob('.hexu-old-*')))
                self.assertFalse(list(root.glob('.hexu-stage-*')))
                self.assertFalse(archive.exists())
                # A corrupt replacement must roll back and restart the working version.
                subprocess.run(['taskkill', '/PID', str(restarted_pid), '/F'], check=True, stdout=subprocess.DEVNULL)
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('fixture.exe', b'not an executable')
                    z.writestr('_internal/build-info.json', json.dumps({'version': '3.0.0', 'commit': 'bad'}))
                with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(exe)):
                    helper = updater._write_helper(work, install, archive, None, 2147483000, ('--port', str(port), '--no-browser'), '3.0.0')
                failed = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper)], capture_output=True, timeout=60)
                self.assertEqual(failed.returncode, 1)
                self.assertEqual(json.loads((work / 'result.json').read_text(encoding='utf-8-sig'))['state'], 'failed')
                self.assertEqual(json.loads((install / '_internal/build-info.json').read_text())['version'], '2.0.0')
                self.assertEqual(hashlib.sha256(model.read_bytes()).hexdigest(), original_hash)
                self.assertFalse(list(root.glob('.hexu-old-*')))
                self.assertFalse(list(root.glob('.hexu-stage-*')))
                for _ in range(40):
                    try:
                        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/build-info.json', timeout=1) as response:
                            self.assertEqual(json.load(response)['version'], '2.0.0')
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    self.fail('Rollback did not restart the working service')
            finally:
                if (install / 'fixture.pid').exists():
                    restarted_pid = int((install / 'fixture.pid').read_text())
                if restarted_pid:
                    subprocess.run(['taskkill', '/PID', str(restarted_pid), '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
