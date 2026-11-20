from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from prepare_assets import install_zip, obtain


class AssetTests(unittest.TestCase):
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
