"""Windows HTTPS fallback boundaries; no real book site or VPN is used."""
import io
import pathlib
import ssl
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import windows_book_http
from book_sources import SourceError, fetch


class WindowsBookHttpTests(unittest.TestCase):
    url = "https://cn.shubaoc.com/search/Fixture/"

    def test_process_output_is_bounded_and_only_its_own_process_is_killed(self):
        process = MagicMock()
        process.stdout = io.BytesIO(b"x" * 102)
        process.poll.return_value = 0
        with patch("windows_book_http.subprocess.Popen") as popen, patch("windows_book_http.threading.Timer") as timer:
            popen.return_value.__enter__.return_value = process
            self.assertEqual(windows_book_http._run(["curl.exe", "-q"], None, 100, 1), (63, b""))
        process.kill.assert_called_once()
        timer.return_value.start.assert_called_once()
        timer.return_value.cancel.assert_called_once()
        self.assertIs(popen.call_args.kwargs["stderr"], windows_book_http.subprocess.DEVNULL)
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_reset_uses_fallback_only_for_compiled_https_sources(self):
        for enabled, trusted, expect in [(True, True, True), (False, True, False), (True, False, False)]:
            with self.subTest(enabled=enabled, trusted=trusted), patch("book_sources.validate_url"), patch("book_sources.urllib.request.build_opener") as opener, patch("windows_book_http.fetch", return_value=(b"Native body", "utf-8")) as native:
                opener.return_value.open.side_effect = URLError(ConnectionResetError())
                if expect:
                    self.assertEqual(fetch(self.url, "cn.shubaoc.com", trusted=trusted, https_only=True, windows_fallback=enabled), "Native body")
                else:
                    with self.assertRaises(SourceError):
                        fetch(self.url, "cn.shubaoc.com", trusted=trusted, https_only=True, windows_fallback=enabled)
                self.assertEqual(native.called, expect)

    def test_certificate_failure_and_http_errors_do_not_retry(self):
        from urllib.error import HTTPError
        for error in [URLError(ssl.SSLCertVerificationError()), HTTPError(self.url, 403, "Forbidden", {}, None)]:
            with patch("book_sources.urllib.request.build_opener") as opener, patch("windows_book_http.fetch") as native:
                opener.return_value.open.side_effect = error
                with self.assertRaises(SourceError):
                    fetch(self.url, "cn.shubaoc.com", trusted=True, https_only=True, windows_fallback=True)
                native.assert_not_called()

    def test_redirects_stay_on_fixed_https_origin_and_post_becomes_get(self):
        responses = [(0, b"HTTP/1.1 302 Found\r\nLocation: /novel/abc/\r\n\r\n"), (0, b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=gbk\r\n\r\nbody")]
        with patch("windows_book_http.client_path", return_value=pathlib.Path("curl.exe")), patch("windows_book_http._run", side_effect=responses) as run:
            body, encoding = windows_book_http.fetch(self.url, lambda u: u, {}, "POST", b"query=Fixture", 1000)
        self.assertEqual((body, encoding), (b"body", "gbk"))
        first, second = run.call_args_list
        self.assertIn("--ipv4", first.args[0])
        self.assertIn("--proto", first.args[0])
        self.assertNotIn("--insecure", first.args[0])
        self.assertNotIn("--location", first.args[0])
        self.assertEqual(first.args[1], b"query=Fixture")
        self.assertIsNone(second.args[1])
        self.assertEqual(second.args[0][-1], "https://cn.shubaoc.com/novel/abc/")
        for target in ["https://evil.example/", "http://cn.shubaoc.com/novel/abc/", "https://user:pass@cn.shubaoc.com/"]:
            with self.subTest(target=target), patch("windows_book_http.client_path", return_value=pathlib.Path("curl.exe")), patch("windows_book_http._run", return_value=(0, ("HTTP/1.1 302 Found\r\nLocation: " + target + "\r\n\r\n").encode())) as run:
                with self.assertRaises(SourceError):
                    windows_book_http.fetch(self.url, lambda u: u, {}, "GET", None, 1000)
                self.assertEqual(run.call_count, 1)

    def test_bounds_errors_and_absent_client(self):
        with patch("windows_book_http.client_path", return_value=None):
            self.assertIsNone(windows_book_http.fetch(self.url, lambda u: u, {}, "GET", None, 1000))
        for code, output in [(56,b""), (60,b""), (0,b"HTTP/1.1 200 OK\r\n\r\n"+b"x"*1001), (0,b"not HTTP")]:
            with self.subTest(code=code), patch("windows_book_http.client_path", return_value=pathlib.Path("curl.exe")), patch("windows_book_http._run", return_value=(code, output)):
                with self.assertRaises(SourceError):
                    windows_book_http.fetch(self.url, lambda u: u, {}, "GET", None, 1000)
        with self.assertRaises(SourceError):
            windows_book_http.fetch("https://evil.example/", lambda u: u, {}, "GET", None, 1000)


if __name__ == "__main__":
    unittest.main()
