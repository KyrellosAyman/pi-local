"""Explicit, loopback-only start/status/stop for the pinned local Qwen server."""

import argparse
from contextlib import contextmanager
import json
import msvcrt
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import psutil


class Refused(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("Redirects are forbidden for the authenticated local endpoint.")


class Launcher:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.config = json.loads((self.directory / "server-config.json").read_text())
        self.state_path = self.directory / "server-state.json"
        self.log_path = self.directory / "server.log"
        c = self.config
        if c["host"] != "127.0.0.1" or c["port"] != 1235:
            raise Refused("Configuration must use 127.0.0.1:1235.")
        self.command = [c["executable"], *c["arguments"],
                        "--model", c["model"], "--mmproj", c["projector"],
                        "--chat-template-file", c["template"],
                        "--host", c["host"], "--port", str(c["port"]),
                        "--alias", c["alias"], "--api-key-file", c["api_key_file"]]

    @contextmanager
    def lock(self):
        with (self.directory / "launcher.lock").open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise Refused("Another launcher operation is running.") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def key(self):
        try:
            lines = Path(self.config["api_key_file"]).read_text().splitlines()
        except OSError:
            raise Refused("Private API key file is missing or unreadable.") from None
        keys = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        if len(keys) != 1:
            raise Refused("Private API key file must contain exactly one key.")
        return keys[0]

    def owned_process(self):
        if not self.state_path.exists():
            return None
        try:
            state = json.loads(self.state_path.read_text())
            process = psutil.Process(state["pid"])
            if (state["command"] != self.command
                    or process.create_time() != state["create_time"]
                    or os.path.normcase(process.exe()) != os.path.normcase(os.path.normpath(self.command[0]))
                    or process.cmdline() != self.command):
                raise Refused("Recorded process identity does not match; leaving it untouched.")
            return process
        except psutil.NoSuchProcess:
            return None
        except (KeyError, ValueError, psutil.AccessDenied):
            raise Refused("Cannot verify recorded process ownership; leaving it untouched.") from None

    def request(self, path):
        request = Request(f'http://127.0.0.1:{self.config["port"]}{path}',
                          headers={"Authorization": "Bearer " + self.key()})
        # Ignore inherited HTTP proxies for this strictly local authenticated endpoint.
        with build_opener(ProxyHandler({}), NoRedirects()).open(request, timeout=3) as response:
            return json.load(response)

    def port_owners(self):
        return {connection.pid for connection in psutil.net_connections(kind="tcp")
                if connection.status == psutil.CONN_LISTEN
                and connection.laddr.port == self.config["port"]}

    def ready(self, process):
        if self.port_owners() != {process.pid}:
            return False
        try:
            healthy = self.request("/health").get("status") == "ok"
            models = self.request("/v1/models").get("data", [])
            return (healthy and [model.get("id") for model in models] == [self.config["alias"]]
                    and self.owned_process() is not None)
        except (URLError, OSError, ValueError):
            return False

    def status(self):
        process = self.owned_process()
        if process is None:
            return {"status": "stopped", "port_owners": sorted(self.port_owners(), key=str)}
        return {"status": "ready" if self.ready(process) else "not-ready", "pid": process.pid,
                "model": self.config["alias"], "log": str(self.log_path)}

    def check_available(self):
        if self.port_owners():
            raise Refused("Port 1235 is occupied; leaving its owner untouched.")
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind((self.config["host"], self.config["port"]))
            except OSError:
                raise Refused("Port 1235 is unavailable; no server started.") from None
        for process in psutil.process_iter(["name"]):
            if (process.info["name"] or "").lower() == "llama-server.exe":
                raise Refused(f"Another llama-server is running (PID {process.pid}); no server started.")

    def start(self):
        self.key()
        process = self.owned_process()
        if process is not None:
            if self.ready(process):
                return {"status": "ready", "pid": process.pid, "reused": True}
            raise Refused(f"Owned server is not ready; inspect {self.log_path}.")
        for name in ("executable", "model", "projector", "template"):
            if not Path(self.config[name]).is_file():
                raise Refused(f"Required {name} file is missing.")
        if not Path(self.config["vendor_directory"]).is_dir():
            raise Refused("Required vendor DLL directory is missing.")
        self.check_available()
        environment = os.environ.copy()
        # Inherited llama options must not override the pinned local configuration.
        for name in list(environment):
            if name.startswith("LLAMA_"):
                del environment[name]
        environment["PATH"] = self.config["vendor_directory"] + os.pathsep + environment.get("PATH", "")
        with self.log_path.open("ab", buffering=0) as log:
            child = subprocess.Popen(self.command, cwd=self.directory, env=environment,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        temporary = self.state_path.with_suffix(".tmp")
        try:
            if child.poll() is not None:
                raise Refused("Original child exited before identity capture.")
            process = psutil.Process(child.pid)
            state = {"pid": child.pid, "create_time": process.create_time(), "command": self.command}
            if (os.path.normcase(process.exe()) != os.path.normcase(os.path.normpath(self.command[0]))
                    or process.cmdline() != self.command):
                raise Refused("Original child identity did not match the launch command.")
            if child.poll() is not None:
                raise Refused("Original child exited during identity capture.")
            temporary.write_text(json.dumps(state, indent=2) + "\n")
            temporary.replace(self.state_path)
        except (Refused, OSError, psutil.Error) as error:
            # Popen retains the original Windows process handle, even if its PID is reused.
            try:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                raise Refused(f"Could not record child PID {child.pid}; original-handle cleanup failed. "
                              f"Inspect {self.log_path}.") from None
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise Refused(f"Could not record child PID {child.pid}: {error} "
                          f"Original child is stopped. Inspect {self.log_path}.") from None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise Refused(f"Server exited ({child.returncode}); inspect {self.log_path}.")
            if self.owned_process() is not None and self.ready(process):
                return {"status": "ready", "pid": child.pid, "reused": False}
            time.sleep(0.5)
        raise Refused(f"Startup exceeded 120 seconds; recorded process left running. Inspect {self.log_path}.")

    def stop(self):
        process = self.owned_process()
        if process is None:
            return {"status": "stopped"}
        if not self.ready(process):
            raise Refused("Owned server is not ready; cannot verify inference inactivity.")
        slots = self.request("/slots")
        if not isinstance(slots, list) or not slots or any(
                not isinstance(slot, dict) or slot.get("is_processing") is not False for slot in slots):
            raise Refused("Inference is active or slot activity is unknown; stop refused.")
        # Recheck identity immediately before terminating; psutil also guards PID reuse.
        process = self.owned_process()
        if process is None:
            return {"status": "stopped"}
        process.terminate()
        try:
            process.wait(timeout=15)
        except psutil.TimeoutExpired:
            raise Refused("Owned server did not stop in 15 seconds; no forced kill attempted.") from None
        self.state_path.unlink(missing_ok=True)
        return {"status": "stopped", "pid": process.pid}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop"))
    arguments = parser.parse_args()
    try:
        launcher = Launcher(Path(__file__).parent)
        with launcher.lock():
            result = getattr(launcher, arguments.command)()
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in ("ready", "stopped") else 1
    except (Refused, OSError, ValueError, psutil.Error) as error:
        print(f"Launcher refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
