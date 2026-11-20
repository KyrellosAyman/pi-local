import json
from io import BytesIO
from email.message import Message
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.request import HTTPHandler, build_opener
from urllib.response import addinfourl

import launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.config = json.loads(Path(__file__).with_name("server-config.json").read_text())
        for key in ("executable", "model", "projector", "template", "api_key_file"):
            path = self.directory / (key + ".fixture")
            path.write_text("test-only-secret" if key == "api_key_file" else "fixture")
            self.config[key] = str(path)
        self.config["vendor_directory"] = str(self.directory)
        (self.directory / "server-config.json").write_text(json.dumps(self.config))
        self.server = launcher.Launcher(self.directory)
        self.process = Mock(pid=123)
        self.process.create_time.return_value = 1234.5
        self.process.exe.return_value = self.config["executable"]
        self.process.cmdline.return_value = self.server.command

    def record(self):
        self.server.state_path.write_text(json.dumps({"pid": 123, "create_time": 1234.5,
                                                     "command": self.server.command}))

    def test_missing_key_refuses_before_spawn(self):
        Path(self.config["api_key_file"]).unlink()
        with patch("launcher.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(launcher.Refused, "key file"):
                self.server.start()
        spawn.assert_not_called()

    def test_occupied_port_refuses_before_spawn(self):
        with patch.object(self.server, "port_owners", return_value={999}), patch("launcher.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(launcher.Refused, "occupied"):
                self.server.start()
        spawn.assert_not_called()

    def test_other_llama_server_refused(self):
        other = Mock(pid=999, info={"name": "llama-server.exe"})
        with patch.object(self.server, "port_owners", return_value=set()), patch("launcher.socket.socket"), \
                patch("launcher.psutil.process_iter", return_value=[other]):
            with self.assertRaisesRegex(launcher.Refused, "Another llama-server"):
                self.server.check_available()

    def test_pid_reuse_or_identity_mismatch_refuses_stop(self):
        for field in ("create_time", "exe", "cmdline"):
            with self.subTest(field=field):
                self.setUp_process_identity()
                self.record()
                getattr(self.process, field).return_value = "mismatch"
                with patch("launcher.psutil.Process", return_value=self.process):
                    with self.assertRaisesRegex(launcher.Refused, "identity"):
                        self.server.stop()
                self.process.terminate.assert_not_called()

    def setUp_process_identity(self):
        self.process.create_time.return_value = 1234.5
        self.process.exe.return_value = self.config["executable"]
        self.process.cmdline.return_value = self.server.command

    def test_matched_running_server_reused_after_health_and_identity(self):
        self.record()
        with patch("launcher.psutil.Process", return_value=self.process), \
                patch.object(self.server, "port_owners", return_value={123}), \
                patch.object(self.server, "request", side_effect=[{"status": "ok"},
                      {"data": [{"id": self.config["alias"]}]}]) as request, \
                patch("launcher.subprocess.Popen") as spawn:
            result = self.server.start()
        self.assertTrue(result["reused"])
        self.assertEqual([call.args[0] for call in request.call_args_list], ["/health", "/v1/models"])
        spawn.assert_not_called()

    def test_status_cannot_adopt_healthy_unowned_port(self):
        with patch.object(self.server, "port_owners", return_value={999}), \
                patch.object(self.server, "request") as request:
            self.assertEqual(self.server.status()["status"], "stopped")
        request.assert_not_called()

    def test_owned_status_rejects_foreign_port_and_model(self):
        self.record()
        with patch("launcher.psutil.Process", return_value=self.process), \
                patch.object(self.server, "port_owners", return_value={999}):
            self.assertEqual(self.server.status()["status"], "not-ready")
        with patch("launcher.psutil.Process", return_value=self.process), \
                patch.object(self.server, "port_owners", return_value={123}), \
                patch.object(self.server, "request", side_effect=[{"status": "ok"},
                      {"data": [{"id": "wrong-model"}]}]):
            self.assertEqual(self.server.status()["status"], "not-ready")

    def test_active_or_unknown_inference_refuses_stop(self):
        self.record()
        for slots in ([{"is_processing": True}], [{}], [], {"error": "unknown"}):
            with self.subTest(slots=slots), patch("launcher.psutil.Process", return_value=self.process), \
                    patch.object(self.server, "ready", return_value=True), \
                    patch.object(self.server, "request", return_value=slots):
                with self.assertRaisesRegex(launcher.Refused, "active or slot activity is unknown"):
                    self.server.stop()
        self.process.terminate.assert_not_called()
        self.assertTrue(self.server.state_path.exists())

    def test_owned_start_and_stop_persists_state_and_environment(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        with patch.object(self.server, "check_available"), \
                patch("launcher.psutil.Process", return_value=self.process), \
                patch.object(self.server, "port_owners", return_value={123}), \
                patch.object(self.server, "request", side_effect=[
                    {"status": "ok"}, {"data": [{"id": self.config["alias"]}]},
                    {"status": "ok"}, {"data": [{"id": self.config["alias"]}]},
                    [{"is_processing": False}]]), \
                patch.dict(os.environ, {"LLAMA_ARG_CTX_SIZE": "5"}), \
                patch("launcher.subprocess.Popen", return_value=child) as spawn:
            self.assertFalse(self.server.start()["reused"])
            state = json.loads(self.server.state_path.read_text())
            self.assertEqual(state["create_time"], 1234.5)
            self.assertNotIn("test-only-secret", self.server.state_path.read_text())
            kwargs = spawn.call_args.kwargs
            self.assertTrue(kwargs["env"]["PATH"].startswith(str(self.directory) + os.pathsep))
            self.assertNotIn("LLAMA_ARG_CTX_SIZE", kwargs["env"])
            self.assertTrue(kwargs["creationflags"] & launcher.subprocess.CREATE_NO_WINDOW)
            self.assertEqual(self.server.stop()["status"], "stopped")
        self.process.terminate.assert_called_once()
        self.process.wait.assert_called_once_with(timeout=15)
        self.assertFalse(self.server.state_path.exists())
        self.assertTrue(self.server.log_path.exists())

    def test_startup_failure_preserves_identity_and_does_not_kill(self):
        child = Mock(pid=123, returncode=1)
        child.poll.side_effect = [None, None, 1]
        with patch.object(self.server, "check_available"), \
                patch("launcher.psutil.Process", return_value=self.process), \
                patch("launcher.subprocess.Popen", return_value=child):
            with self.assertRaisesRegex(launcher.Refused, "Server exited"):
                self.server.start()
        self.assertTrue(self.server.state_path.exists())
        self.process.terminate.assert_not_called()
        child.kill.assert_not_called()

    def test_early_exit_and_pid_reuse_never_records_ownership(self):
        for polls in ([1, 1], [None, 1, 1]):
            with self.subTest(polls=polls):
                child = Mock(pid=123, returncode=1)
                child.poll.side_effect = polls
                self.process.create_time.return_value = 9999
                with patch.object(self.server, "check_available"), \
                        patch("launcher.psutil.Process", return_value=self.process) as lookup, \
                        patch("launcher.subprocess.Popen", return_value=child):
                    with self.assertRaisesRegex(launcher.Refused, "exited"):
                        self.server.start()
                self.assertFalse(self.server.state_path.exists())
                self.assertLessEqual(lookup.call_count, 1)
                if polls[0] == 1:
                    lookup.assert_not_called()
                child.terminate.assert_not_called()
                self.process.terminate.assert_not_called()

    def test_identity_mismatch_at_capture_refuses_and_cleans_original_child(self):
        for field in ("exe", "cmdline"):
            with self.subTest(field=field):
                self.setUp_process_identity()
                getattr(self.process, field).return_value = "wrong"
                child = Mock(pid=123)
                child.poll.return_value = None
                with patch.object(self.server, "check_available"), \
                        patch("launcher.psutil.Process", return_value=self.process), \
                        patch("launcher.subprocess.Popen", return_value=child):
                    with self.assertRaisesRegex(launcher.Refused, "identity"):
                        self.server.start()
                self.assertFalse(self.server.state_path.exists())
                child.terminate.assert_called_once()
                child.wait.assert_called_once_with(timeout=15)
                self.process.terminate.assert_not_called()

    def test_record_write_and_replace_failure_clean_original_handle(self):
        for operation in ("write_text", "replace"):
            with self.subTest(operation=operation):
                child = Mock(pid=123)
                child.poll.return_value = None
                with patch.object(self.server, "check_available"), \
                        patch("launcher.psutil.Process", return_value=self.process) as lookup, \
                        patch("launcher.subprocess.Popen", return_value=child), \
                        patch.object(Path, operation, side_effect=OSError("test record failure")):
                    with self.assertRaisesRegex(launcher.Refused, "record"):
                        self.server.start()
                self.assertFalse(self.server.state_path.exists())
                self.assertFalse(self.server.state_path.with_suffix(".tmp").exists())
                lookup.assert_called_once_with(123)
                child.terminate.assert_called_once()
                child.wait.assert_called_once_with(timeout=15)
                self.process.terminate.assert_not_called()

    def test_redirect_does_not_send_second_request_or_secret(self):
        requests = []

        class RedirectTransport(HTTPHandler):
            def http_open(self, request):
                requests.append((request.full_url, request.get_header("Authorization")))
                headers = Message()
                headers["Location"] = "http://outside.invalid/steal"
                response = addinfourl(BytesIO(b""), headers, request.full_url, 302)
                response.msg = "Found"
                return response

        def opener(*handlers):
            return build_opener(*handlers, RedirectTransport())

        with patch("launcher.build_opener", side_effect=opener):
            with self.assertRaisesRegex(launcher.URLError, "Redirects"):
                self.server.request("/health")
        self.assertEqual(requests, [("http://127.0.0.1:1235/health", "Bearer test-only-secret")])

    def test_startup_timeout_preserves_process(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        with patch.object(self.server, "check_available"), \
                patch("launcher.psutil.Process", return_value=self.process), \
                patch("launcher.subprocess.Popen", return_value=child), \
                patch("launcher.time.monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(launcher.Refused, "120 seconds"):
                self.server.start()
        self.assertTrue(self.server.state_path.exists())
        self.process.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
