from hashlib import sha256
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from configure import checked_workspace_bins
from prepare_assets import digest, install_audio, install_zip, obtain


class AssetTests(unittest.TestCase):
    def test_workspace_tool_paths_require_the_pinned_binary(self):
        data = b"verified"
        tools = {"ripgrep": {"member": "release/rg.exe", "member_sha256": sha256(data).hexdigest()}}
        with TemporaryDirectory() as folder:
            cache = Path(folder)
            self.assertEqual(checked_workspace_bins(cache, tools), [])
            executable = cache / "ripgrep/release/rg.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(data)
            self.assertEqual(checked_workspace_bins(cache, tools), [str(executable.parent)])
            executable.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "pinned binary"):
                checked_workspace_bins(cache, tools)

    def test_offline_assets_must_match_byte_count_and_digest(self):
        data = b"verified"
        asset = {"file": "asset.bin", "bytes": len(data), "sha256": sha256(data).hexdigest()}
        with TemporaryDirectory() as directory:
            cache = Path(directory)
            target = cache / asset["file"]
            with self.assertRaises(FileNotFoundError):
                obtain(cache, asset, False)
            target.write_bytes(data)
            self.assertEqual(obtain(cache, asset, False), target)
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                obtain(cache, asset, False)

    def test_download_restarts_from_bytes_retained_after_connection_failure(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory)
            asset = {"file": "release.bin", "bytes": 6, "sha256": sha256(b"abcdef").hexdigest(),
                     "url": "https://example.invalid/release.bin"}
            partial = cache / "release.bin.part"
            calls = []

            def curl(arguments):
                calls.append(partial.stat().st_size if partial.exists() else 0)
                self.assertEqual(arguments[arguments.index("--continue-at") + 1], "-")
                self.assertNotIn("--retry", arguments)
                with partial.open("ab") as stream:
                    stream.write(b"abc" if len(calls) == 1 else b"def")
                return CompletedProcess(arguments, 28 if len(calls) == 1 else 0)

            with patch("prepare_assets.subprocess.run", side_effect=curl):
                self.assertEqual(obtain(cache, asset, True).read_bytes(), b"abcdef")
            self.assertEqual(calls, [0, 3])
            self.assertFalse(partial.exists())

    def test_extracted_runtime_must_match_the_archive(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory)
            archive, runtime = cache / "engine.zip", cache / "runtime"
            with ZipFile(archive, "w") as fixture:
                fixture.writestr("engine.dll", "verified")
            install_zip(archive, runtime)
            install_zip(archive, runtime)
            (runtime / "engine.dll").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "runtime file differs"):
                install_zip(archive, runtime)
            (runtime / "engine.dll").write_text("verified")
            (runtime / "unexpected.dll").touch()
            with self.assertRaisesRegex(ValueError, "runtime differs"):
                install_zip(archive, runtime)

    def test_optional_audio_installs_the_complete_pinned_runtime(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            model = "parakeet-tdt-0.6b-v3.q8_0.gguf"
            ffmpeg = b"new encoder"
            previous = b"old encoder"
            fixture = {
                "ffmpeg": {"ffmpeg.exe": sha256(ffmpeg).hexdigest()},
                "native_bin": {"nemo-speech.exe": sha256(b"speech").hexdigest()},
                "model": sha256(b"model").hexdigest(),
                "yamnet": {"yamnet.onnx": sha256(b"classifier").hexdigest()},
                "legacy_ffmpeg": {"ffmpeg/ffmpeg.exe": sha256(previous).hexdigest()},
                "downloads": {},
            }
            for name, executable, data in (("ffmpeg", "ffmpeg.exe", ffmpeg), ("nemo-speech", "nemo-speech.exe", b"speech")):
                archive = root / f"{name}.zip"
                with ZipFile(archive, "w") as package:
                    package.writestr(f"bin/{executable}", data)
                fixture["downloads"][name] = {"file": archive.name, "bytes": archive.stat().st_size,
                                               "sha256": digest(archive), "bin": "bin"}
            for name, data in ((model, b"model"), ("yamnet/yamnet.onnx", b"classifier")):
                source = root / Path(name).name
                fixture["downloads"][name] = {"file": source.name, "bytes": len(data), "sha256": sha256(data).hexdigest()}
                if name == model:
                    source.write_bytes(data)
            old = runtime / "ffmpeg/ffmpeg.exe"
            old.parent.mkdir(parents=True)
            old.write_bytes(previous)
            with self.assertRaises(FileNotFoundError):
                install_audio(root, runtime, fixture, False)
            self.assertEqual(old.read_bytes(), previous)
            self.assertFalse((runtime / model).exists())
            (root / "yamnet.onnx").write_bytes(b"classifier")
            install_audio(root, runtime, fixture, False)
            self.assertEqual(old.read_bytes(), ffmpeg)
            self.assertEqual((runtime / "nemo-speech/nemo-speech.exe").read_bytes(), b"speech")
            self.assertEqual((runtime / model).read_bytes(), b"model")
            install_audio(root / "absent-cache", runtime, fixture, False)
            old.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "does not match its pin"):
                install_audio(root, runtime, fixture, False)
