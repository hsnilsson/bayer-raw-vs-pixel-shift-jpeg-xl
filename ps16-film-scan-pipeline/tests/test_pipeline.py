from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline as pipeline_module  # noqa: E402


class SyntheticPipeline(pipeline_module.Pipeline):
    def __init__(self, *args, fake_adc_script: Path, **kwargs):
        self.fake_adc_script = fake_adc_script
        super().__init__(*args, **kwargs)

    def read_metadata(self, paths: list[Path]) -> None:
        for shot, path in enumerate(sorted(paths), start=1):
            self.db.execute(
                "UPDATE raw_files SET metadata_done=1,group_id='42',shot=?,expected=16 WHERE path=?",
                (shot, str(path)),
            )
        self.db.execute(
            "INSERT INTO groups(group_id,expected,updated_at) VALUES('42',16,?) "
            "ON CONFLICT(group_id) DO UPDATE SET updated_at=excluded.updated_at",
            (pipeline_module.utc_now(),),
        )
        self.db.commit()

    def invoke_pixelshift(self, outputs: list[Path]) -> None:
        for output in outputs:
            output.write_bytes(b"synthetic pixel shift dng")

    def wait_stable(self, paths, timeout: int) -> None:  # noqa: ANN001
        if not all(Path(path).is_file() for path in paths):
            raise FileNotFoundError("synthetic output missing")

    def validate_dng(self, path: Path, *, expect_jxl: bool = False):  # noqa: ANN201
        return {
            "ok": path.is_file() and path.stat().st_size > 0,
            "width": 9600,
            "height": 6376,
            "compression": "JPEG XL" if expect_jxl else "Uncompressed",
            "jxl_distance": None,
        }

    def adc_command(self, source: Path, destination: Path, level: str, effort: int) -> list[str]:
        return [sys.executable, str(self.fake_adc_script), str(source), str(destination)]


class Ps16ScanPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        for name in ("pixelshift.exe", "adc.exe", "exiftool.exe"):
            (self.tools / name).write_bytes(b"tool")
        self.fake_adc = self.root / "fake_adc.py"
        self.fake_adc.write_text(
            "import shutil,sys\n"
            "from pathlib import Path\n"
            "source,destination=Path(sys.argv[1]),Path(sys.argv[2])\n"
            "destination.mkdir(parents=True,exist_ok=True)\n"
            "shutil.copyfile(source,destination/source.name)\n",
            encoding="utf-8",
        )
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config()), encoding="utf-8")

    def config(self) -> dict:
        return {
            "schema_version": 1,
            "batch": {"id": "roll-test", "film_stock": "Synthetic 100", "filmlab_profile": "Test"},
            "paths": {
                "incoming": str(self.incoming),
                "work": str(self.root / "work"),
                "archive": str(self.root / "archive"),
                "filmlab_staging": str(self.root / "stage"),
                "positive_inbox": str(self.root / "stage" / "positive-exports"),
                "positives": str(self.root / "positives"),
                "previews": str(self.root / "previews"),
                "errors": str(self.root / "work" / "errors"),
                "quarantine": str(self.root / "quarantine"),
            },
            "tools": {
                "pixelshift2dng": str(self.tools / "pixelshift.exe"),
                "adobe_dng_converter": str(self.tools / "adc.exe"),
                "exiftool": str(self.tools / "exiftool.exe"),
            },
            "watch": {"poll_seconds": 1, "stable_seconds": 0, "output_timeout_seconds": 5},
            "jpeg_xl_profiles": {
                "archive": {"enabled": True, "level": "d005", "effort": 7, "required_for_cleanup": True},
            },
            "filmlab": {
                "enabled": True,
                "input_profile": "archive",
                "use_hardlinks_when_possible": True,
                "launch_command": [],
                "positive_extensions": [".png"],
            },
            "previews": {"enabled": True, "max_long_edge": 100, "jpeg_quality": 80},
            "cleanup": {"enabled": True, "require_positive": True, "retention_groups": 0, "prune_mode": "move"},
        }

    def make_raws(self) -> None:
        for number in range(1, 17):
            (self.incoming / f"DSC{number:04d}.ARW").write_bytes(bytes([number]))

    def open_pipeline(self) -> SyntheticPipeline:
        config = pipeline_module.load_config(self.config_path)
        pipeline = SyntheticPipeline(config, fake_adc_script=self.fake_adc)
        self.addCleanup(pipeline.close)
        return pipeline

    def test_parses_sony_pixel_shift_info(self) -> None:
        self.assertEqual(
            pipeline_module.parse_pixelshift_info("Group 17163427, Shot 3/16 (0x3)"),
            ("17163427", 3, 16),
        )

    def test_ascii_name_is_stable_and_safe(self) -> None:
        self.assertEqual(pipeline_module.ascii_name("Rulle åäö / bild 1"), "Rulle_bild_1")

    def test_config_rejects_archive_inside_incoming(self) -> None:
        config = self.config()
        config["paths"]["archive"] = str(self.incoming / "archive")
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "paths.archive"):
            pipeline_module.load_config(self.config_path)

    def test_config_rejects_invalid_cleanup_settings(self) -> None:
        for key, value in (("retention_groups", -1), ("prune_mode", "erase")):
            with self.subTest(key=key):
                config = self.config()
                config["cleanup"][key] = value
                self.config_path.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    pipeline_module.load_config(self.config_path)

    def test_existing_queue_schema_gains_cleaned_at(self) -> None:
        work = self.root / "work"
        work.mkdir()
        db = pipeline_module.sqlite3.connect(work / "queue.sqlite3")
        try:
            db.execute(
                "CREATE TABLE groups (group_id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'discovered',"
                "expected INTEGER NOT NULL DEFAULT 16,dng_name TEXT,attempts INTEGER NOT NULL DEFAULT 0,"
                "error TEXT,approved_at TEXT,updated_at TEXT NOT NULL)"
            )
            db.commit()
        finally:
            db.close()
        config = pipeline_module.load_config(self.config_path)
        pipeline = SyntheticPipeline(config, fake_adc_script=self.fake_adc)
        try:
            columns = {row[1] for row in pipeline.db.execute("PRAGMA table_info(groups)")}
            self.assertIn("cleaned_at", columns)
        finally:
            pipeline.close()

    def test_synthetic_restartable_flow_and_retention_prune(self) -> None:
        self.make_raws()
        pipeline = self.open_pipeline()

        pipeline.process_once()

        self.assertEqual(pipeline.group_status("42"), "awaiting_positive")
        source = self.incoming / "DSC0001-DSC0016.dng"
        self.assertTrue(source.is_file())
        self.assertTrue((self.root / "archive" / "archive" / source.name).is_file())
        self.assertFalse((self.root / "archive" / "view").exists())
        output_count = pipeline.db.execute("SELECT COUNT(*) FROM outputs WHERE group_id='42'").fetchone()[0]

        pipeline.process_once()
        self.assertEqual(
            pipeline.db.execute("SELECT COUNT(*) FROM outputs WHERE group_id='42'").fetchone()[0], output_count
        )

        from PIL import Image

        staged = Path(
            pipeline.db.execute(
                "SELECT path FROM outputs WHERE group_id='42' AND kind='filmlab_staging'"
            ).fetchone()[0]
        )
        positive_inbox = self.root / "stage" / "positive-exports"
        Image.new("RGB", (40, 20), (120, 80, 40)).save(positive_inbox / f"{staged.stem}.png")
        pipeline.process_once()

        self.assertEqual(pipeline.group_status("42"), "positive_verified")
        self.assertTrue((self.root / "previews" / f"{staged.stem}.jpg").is_file())
        pipeline.approve("42")
        with self.assertRaises(RuntimeError):
            pipeline.prune("wrong-token")
        self.assertTrue((self.incoming / "DSC0001.ARW").is_file())

        pipeline.config["cleanup"]["retention_groups"] = 1
        pipeline.prune("roll-test")
        self.assertEqual(pipeline.group_status("42"), "approved")
        self.assertTrue((self.incoming / "DSC0001.ARW").is_file())

        pipeline.config["cleanup"]["retention_groups"] = 0
        pipeline.prune("roll-test")

        self.assertEqual(pipeline.group_status("42"), "quarantined")
        self.assertFalse((self.incoming / "DSC0001.ARW").exists())
        self.assertTrue((self.root / "quarantine" / "42" / "DSC0001.ARW").is_file())
        self.assertTrue(source.is_file(), "derived DNG must not be moved with camera raws")

        pipeline.config["cleanup"]["prune_mode"] = "delete"
        pipeline.prune("roll-test")
        self.assertEqual(pipeline.group_status("42"), "cleaned")
        self.assertFalse((self.root / "quarantine" / "42" / "DSC0001.ARW").exists())


if __name__ == "__main__":
    unittest.main()
