from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent


def require_level(value: str) -> str:
    if value == "lossless" or (len(value) >= 3 and value.startswith("d") and value[1:].isdigit()):
        return value
    raise ValueError(
        f"invalid JXL level: {value!r}; use 'lossless' or names like d003, d005, d010"
    )


def distance_for_level(level: str) -> str | None:
    require_level(level)
    if level == "lossless":
        return None
    return f"{int(level[1:]) / 100:.2f}"


ASCII_COMPONENT = re.compile(r"^[\x20-\x7e]+$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_files (
  path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
  stable_since REAL NOT NULL, metadata_done INTEGER NOT NULL DEFAULT 0,
  group_id TEXT, shot INTEGER, expected INTEGER, sha256 TEXT
);
CREATE TABLE IF NOT EXISTS groups (
  group_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'discovered',
  expected INTEGER NOT NULL DEFAULT 16, dng_name TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT, approved_at TEXT, cleaned_at TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outputs (
  group_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
  size INTEGER NOT NULL, sha256 TEXT NOT NULL, verified_at TEXT NOT NULL,
  PRIMARY KEY(group_id, kind)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, group_id TEXT,
  level TEXT NOT NULL, message TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("config schema_version must be 1")
    for key in ("incoming", "work", "archive", "errors", "quarantine"):
        if key not in config.get("paths", {}):
            raise ValueError(f"missing paths.{key}")
    for key in ("pixelshift2dng", "adobe_dng_converter", "exiftool"):
        if key not in config.get("tools", {}):
            raise ValueError(f"missing tools.{key}")
    if not config.get("batch", {}).get("id"):
        raise ValueError("batch.id must not be empty")
    profiles = config.get("jpeg_xl_profiles", {})
    if not profiles or not any(item.get("enabled", True) for item in profiles.values()):
        raise ValueError("at least one jpeg_xl_profiles entry must be enabled")
    for name, profile in profiles.items():
        if profile.get("enabled", True):
            require_level(str(profile["level"]))
            effort = int(profile.get("effort", 7))
            if not 1 <= effort <= 9:
                raise ValueError(f"jpeg_xl_profiles.{name}.effort must be 1..9")
    staging = config.get("paths", {}).get("filmlab_staging")
    if config.get("filmlab", {}).get("enabled") and staging:
        if any(not ASCII_COMPONENT.match(part) for part in expand_path(staging).parts):
            raise ValueError("paths.filmlab_staging must contain ASCII characters only")
    if config.get("filmlab", {}).get("enabled"):
        for key in ("filmlab_staging", "positive_inbox", "positives"):
            if key not in config["paths"]:
                raise ValueError(f"FilmLab integration requires paths.{key}")
    if config.get("previews", {}).get("enabled", True) and "previews" not in config["paths"]:
        raise ValueError("preview generation requires paths.previews")
    if not config.get("filmlab", {}).get("enabled") and config.get("cleanup", {}).get("require_positive", True):
        raise ValueError("cleanup.require_positive must be false when FilmLab integration is disabled")
    cleanup = config.get("cleanup", {})
    if cleanup.get("retention_groups") is not None:
        retention_groups = int(cleanup["retention_groups"])
        if retention_groups < 0:
            raise ValueError("cleanup.retention_groups must be >= 0")
    if cleanup.get("prune_mode", "move") not in {"move", "delete"}:
        raise ValueError("cleanup.prune_mode must be 'move' or 'delete'")
    incoming = expand_path(config["paths"]["incoming"])
    for key in ("work", "archive", "errors", "quarantine"):
        candidate = expand_path(config["paths"][key])
        if incoming == candidate or incoming in candidate.parents or candidate in incoming.parents:
            raise ValueError(f"paths.{key} must not contain or be contained by paths.incoming")
    return config


class Pipeline:
    def __init__(self, config: dict[str, Any], *, dry_run: bool = False, exclusive: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.paths = {key: expand_path(value) for key, value in config["paths"].items()}
        self.tools = {key: expand_path(value) for key, value in config["tools"].items()}
        self.work = self.paths["work"]
        if dry_run:
            self.db = sqlite3.connect(":memory:")
        else:
            self.work.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.work / "queue.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        raw_columns = {row[1] for row in self.db.execute("PRAGMA table_info(raw_files)")}
        if "sha256" not in raw_columns:
            self.db.execute("ALTER TABLE raw_files ADD COLUMN sha256 TEXT")
        group_columns = {row[1] for row in self.db.execute("PRAGMA table_info(groups)")}
        if "cleaned_at" not in group_columns:
            self.db.execute("ALTER TABLE groups ADD COLUMN cleaned_at TEXT")
        self.db.commit()
        self._lock_handle = None
        if exclusive and not dry_run:
            self.acquire_process_lock()

    def close(self) -> None:
        if self._lock_handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._lock_handle.seek(0)
                    msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._lock_handle.close()
                self._lock_handle = None
        self.db.close()

    def acquire_process_lock(self) -> None:
        lock_path = self.work / "pipeline.lock"
        handle = lock_path.open("a+b")
        if lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError(f"another watcher is already using {self.work}") from exc
        self._lock_handle = handle

    def event(self, message: str, *, group_id: str | None = None, level: str = "INFO") -> None:
        line = f"{utc_now()} {level}"
        if group_id:
            line += f" [{group_id}]"
        line += f" {message}"
        print(line, flush=True)
        if not self.dry_run:
            self.db.execute(
                "INSERT INTO events(at, group_id, level, message) VALUES (?, ?, ?, ?)",
                (utc_now(), group_id, level, message),
            )
            self.db.commit()
            log = self.work / "pipeline.log"
            with log.open("a", encoding="utf-8") as target:
                target.write(line + "\n")

    def check_environment(self, *, require_incoming: bool = True) -> None:
        if require_incoming and not self.paths["incoming"].is_dir():
            raise FileNotFoundError(f"incoming folder not found: {self.paths['incoming']}")
        for key in ("pixelshift2dng", "adobe_dng_converter", "exiftool"):
            if not self.tools[key].is_file():
                raise FileNotFoundError(f"tools.{key} not found: {self.tools[key]}")
        incoming = self.paths["incoming"]
        # PixelShift2DNG's GUI automation is intentionally scoped to one flat roll folder.
        nested = [path for path in incoming.rglob("*.ARW") if path.parent != incoming]
        if nested:
            raise ValueError(f"incoming must be flat; found nested ARW: {nested[0]}")

    def check_free_space(self) -> None:
        minimum = float(self.config.get("watch", {}).get("minimum_free_gib", 0))
        if minimum <= 0:
            return
        for key in ("incoming", "work", "archive"):
            candidate = self.paths[key]
            while not candidate.exists() and candidate != candidate.parent:
                candidate = candidate.parent
            free_gib = shutil.disk_usage(candidate).free / 1024**3
            if free_gib < minimum:
                raise RuntimeError(
                    f"free-space guard: {key} volume has {free_gib:.1f} GiB, below {minimum:.1f} GiB"
                )

    def discover(self) -> list[Path]:
        now = time.time()
        stable_seconds = float(self.config.get("watch", {}).get("stable_seconds", 15))
        found = sorted(self.paths["incoming"].glob("*.ARW"))
        found += sorted(self.paths["incoming"].glob("*.arw"))
        unique = list(dict.fromkeys(path.resolve() for path in found if path.is_file()))
        for path in unique:
            stat = path.stat()
            row = self.db.execute("SELECT size, mtime_ns FROM raw_files WHERE path=?", (str(path),)).fetchone()
            if row and row["size"] == stat.st_size and row["mtime_ns"] == stat.st_mtime_ns:
                continue
            # Camera timestamps can predate an in-progress copy. Every new or changed
            # file must survive a full observation window regardless of its mtime.
            stable_since = now
            self.db.execute(
                "INSERT INTO raw_files(path,size,mtime_ns,stable_since,metadata_done) VALUES(?,?,?,?,0) "
                "ON CONFLICT(path) DO UPDATE SET size=excluded.size,mtime_ns=excluded.mtime_ns,"
                "stable_since=excluded.stable_since,metadata_done=0,group_id=NULL,shot=NULL,expected=NULL",
                (str(path), stat.st_size, stat.st_mtime_ns, stable_since),
            )
        self.db.commit()
        ready = self.db.execute(
            "SELECT path FROM raw_files WHERE metadata_done=0 AND size>0 AND ?-stable_since>=? ORDER BY path",
            (now, stable_seconds),
        ).fetchall()
        return [Path(row["path"]) for row in ready]

    def read_metadata(self, paths: list[Path]) -> None:
        for chunk_start in range(0, len(paths), 128):
            chunk = paths[chunk_start : chunk_start + 128]
            command = [
                str(self.tools["exiftool"]), "-json", "-FileName", "-PixelShiftInfo",
                "-SequenceNumber", "-ReleaseMode", *map(str, chunk),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0:
                raise RuntimeError(f"ExifTool grouping failed: {completed.stderr.strip()}")
            rows = json.loads(completed.stdout or "[]")
            by_source = {str(Path(row.get("SourceFile", "")).resolve()).lower(): row for row in rows}
            by_name = {str(row.get("FileName", "")).lower(): row for row in rows}
            for path in chunk:
                row = by_source.get(str(path.resolve()).lower()) or by_name.get(path.name.lower(), {})
                parsed = parse_pixelshift_info(row.get("PixelShiftInfo"))
                if parsed:
                    group_id, shot, expected = parsed
                    self.db.execute(
                        "UPDATE raw_files SET metadata_done=1,group_id=?,shot=?,expected=? WHERE path=?",
                        (group_id, shot, expected, str(path)),
                    )
                    self.db.execute(
                        "INSERT INTO groups(group_id,expected,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(group_id) DO UPDATE SET expected=excluded.expected,updated_at=excluded.updated_at",
                        (group_id, expected, utc_now()),
                    )
                else:
                    self.db.execute("UPDATE raw_files SET metadata_done=1 WHERE path=?", (str(path),))
            self.db.commit()

    def complete_groups(self) -> list[str]:
        rows = self.db.execute(
            "SELECT g.group_id,g.expected,COUNT(r.path) AS files,COUNT(DISTINCT r.shot) AS shots,"
            "MIN(r.shot) AS first_shot,MAX(r.shot) AS last_shot "
            "FROM groups g JOIN raw_files r ON r.group_id=g.group_id "
            "WHERE g.expected=16 GROUP BY g.group_id "
            "HAVING files=16 AND shots=16 AND first_shot=1 AND last_shot=16 "
            "AND MIN(r.expected)=16 AND MAX(r.expected)=16 ORDER BY g.group_id"
        ).fetchall()
        return [row["group_id"] for row in rows]

    def group_files(self, group_id: str) -> list[Path]:
        rows = self.db.execute(
            "SELECT path FROM raw_files WHERE group_id=? ORDER BY shot,path", (group_id,)
        ).fetchall()
        return [Path(row["path"]) for row in rows]

    def expected_dng(self, group_id: str) -> Path:
        files = self.group_files(group_id)
        if len(files) != 16:
            raise RuntimeError(f"group has {len(files)} files, expected 16")
        return self.paths["incoming"] / f"{files[0].stem}-{files[-1].stem}.dng"

    def group_status(self, group_id: str) -> str:
        row = self.db.execute("SELECT status FROM groups WHERE group_id=?", (group_id,)).fetchone()
        return row["status"] if row else "missing"

    def set_group(self, group_id: str, status: str, *, error: str | None = None, dng_name: str | None = None) -> None:
        if self.dry_run:
            return
        self.db.execute(
            "UPDATE groups SET status=?,error=?,dng_name=COALESCE(?,dng_name),updated_at=? WHERE group_id=?",
            (status, error, dng_name, utc_now(), group_id),
        )
        self.db.commit()

    def wait_stable(self, paths: Iterable[Path], timeout: int) -> None:
        targets = list(paths)
        previous: dict[Path, tuple[int, int]] = {}
        stable_passes = 0
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = {
                path: (path.stat().st_size, path.stat().st_mtime_ns)
                for path in targets if path.is_file() and path.stat().st_size > 0
            }
            if len(current) == len(targets) and current == previous:
                stable_passes += 1
                if stable_passes >= 3:
                    return
            else:
                stable_passes = 0
            previous = current
            time.sleep(2)
        missing = [str(path) for path in targets if not path.is_file()]
        raise TimeoutError(f"output did not stabilize; missing={missing}")

    def invoke_pixelshift(self, outputs: list[Path]) -> None:
        helper = ROOT / "invoke_pixelshift2dng.ps1"
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper),
            "-Executable", str(self.tools["pixelshift2dng"]), "-InputFolder", str(self.paths["incoming"]),
            "-ReuseExisting",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise RuntimeError(f"PixelShift2DNG launch failed: {completed.stderr.strip()}")
        self.wait_stable(outputs, int(self.config.get("watch", {}).get("output_timeout_seconds", 1800)))

    def validate_dng(self, path: Path, *, expect_jxl: bool = False) -> dict[str, Any]:
        completed = subprocess.run(
            [str(self.tools["exiftool"]), "-json", "-validate", "-ImageWidth", "-ImageHeight",
             "-Compression", "-JXLDistance", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        rows = json.loads(completed.stdout or "[]")
        row = rows[0] if rows else {}
        width, height = int(row.get("ImageWidth") or 0), int(row.get("ImageHeight") or 0)
        compression = str(row.get("Compression") or "")
        ok = completed.returncode == 0 and path.is_file() and path.stat().st_size > 0 and width > 0 and height > 0
        if expect_jxl:
            ok = ok and "jpeg xl" in compression.lower()
        return {"ok": ok, "width": width, "height": height, "compression": compression,
                "jxl_distance": row.get("JXLDistance"), "validate": row.get("Validate")}

    def record_output(self, group_id: str, kind: str, path: Path) -> None:
        digest = sha256_file(path)
        if not self.dry_run:
            self.db.execute(
                "INSERT OR REPLACE INTO outputs(group_id,kind,path,size,sha256,verified_at) VALUES(?,?,?,?,?,?)",
                (group_id, kind, str(path), path.stat().st_size, digest, utc_now()),
            )
            self.db.commit()
        self.event(f"verified {kind}: {path.name}, {path.stat().st_size} bytes, sha256={digest}", group_id=group_id)

    def ensure_source_dngs(self, groups: list[str]) -> None:
        missing = [self.expected_dng(group_id) for group_id in groups if not self.expected_dng(group_id).is_file()]
        if self.dry_run:
            for path in missing:
                self.event(f"DRY RUN would create PixelShift DNG {path.name}")
            return
        if missing:
            self.event(f"starting PixelShift2DNG for {len(missing)} complete group(s)")
            self.invoke_pixelshift(missing)
        for group_id in groups:
            source = self.expected_dng(group_id)
            verification = self.validate_dng(source)
            if not verification["ok"]:
                raise RuntimeError(f"source DNG verification failed: {source}: {verification}")
            self.record_output(group_id, "source_dng", source)
            self.set_group(group_id, "dng_verified", dng_name=source.name)

    def adc_command(self, source: Path, destination: Path, level: str, effort: int) -> list[str]:
        command = [str(self.tools["adobe_dng_converter"])]
        if level == "lossless":
            command.append("-losslessJXL")
        else:
            command.extend(["-lossy", "-jxl_effort", str(effort), "-jxl_distance", distance_for_level(level) or ""])
        command.extend(["-d", str(destination), str(source)])
        return command

    def ensure_profiles(self, group_id: str) -> None:
        source = self.expected_dng(group_id)
        for name, profile in self.config["jpeg_xl_profiles"].items():
            if not profile.get("enabled", True):
                continue
            final_dir = self.paths["archive"] / name
            final = final_dir / source.name
            if self.dry_run:
                self.event(f"DRY RUN would create {name}/{source.name}", group_id=group_id)
                continue
            existing = self.db.execute(
                "SELECT path,size,sha256 FROM outputs WHERE group_id=? AND kind=?", (group_id, f"jxl:{name}")
            ).fetchone()
            if existing and final.is_file() and final.stat().st_size == existing["size"] and sha256_file(final) == existing["sha256"]:
                continue
            temp_dir = self.work / "adc-temp" / group_id / name
            temp_dir.mkdir(parents=True, exist_ok=True)
            temporary = temp_dir / source.name
            if temporary.exists():
                temporary.unlink()
            completed = subprocess.run(
                self.adc_command(source, temp_dir, str(profile["level"]), int(profile.get("effort", 7))),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if completed.returncode != 0:
                raise RuntimeError(f"ADC {name} failed: {completed.stderr.strip()}")
            self.wait_stable([temporary], 120)
            generated = list(temp_dir.glob("*.dng")) + list(temp_dir.glob("*.DNG"))
            if len(dict.fromkeys(path.resolve() for path in generated)) != 1 or not temporary.is_file():
                raise RuntimeError(f"ADC {name} produced an unexpected DNG count: {len(generated)}")
            verification = self.validate_dng(temporary, expect_jxl=True)
            if not verification["ok"]:
                raise RuntimeError(f"ADC {name} verification failed: {verification}")
            expected_distance = 0.0 if profile["level"] == "lossless" else float(distance_for_level(str(profile["level"])) or 0)
            actual_distance = verification.get("jxl_distance")
            if actual_distance is not None and abs(float(actual_distance) - expected_distance) > 0.001:
                raise RuntimeError(
                    f"ADC {name} JXL distance mismatch: expected {expected_distance}, got {actual_distance}"
                )
            final_dir.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, final)
            verification = self.validate_dng(final, expect_jxl=True)
            if not verification["ok"]:
                raise RuntimeError(f"published ADC {name} verification failed: {verification}")
            self.record_output(group_id, f"jxl:{name}", final)
        self.set_group(group_id, "profiles_verified")

    def stage_filmlab(self, group_id: str) -> None:
        settings = self.config.get("filmlab", {})
        if not settings.get("enabled"):
            self.set_group(group_id, "verified")
            return
        profile = settings.get("input_profile", "archive")
        kind = "source_dng" if profile == "source" else f"jxl:{profile}"
        row = self.db.execute(
            "SELECT path,sha256 FROM outputs WHERE group_id=? AND kind=?", (group_id, kind)
        ).fetchone()
        if not row:
            raise RuntimeError(f"FilmLab input profile is not verified: {profile}")
        source = Path(row["path"])
        staging = self.paths["filmlab_staging"]
        staging.mkdir(parents=True, exist_ok=True)
        safe_name = ascii_name(f"{self.config['batch']['id']}_{source.stem}.dng")
        target = staging / safe_name
        if target.exists() and (
            target.stat().st_size != source.stat().st_size or sha256_file(target) != row["sha256"]
        ):
            target.unlink()
        if not target.exists():
            if settings.get("use_hardlinks_when_possible", True):
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
            else:
                shutil.copy2(source, target)
        batch_manifest = {
            "batch": self.config["batch"], "group_id": group_id,
            "input": str(target), "export_to": str(self.paths["positive_inbox"]),
            "instruction": "Import input in FilmLab, apply the named roll profile, and export using the same filename stem.",
        }
        atomic_json(staging / "filmlab_batch.json", batch_manifest)
        self.paths["positive_inbox"].mkdir(parents=True, exist_ok=True)
        self.record_output(group_id, "filmlab_staging", target)
        self.set_group(group_id, "awaiting_positive")
        launch = [str(value).format(staging_dir=str(staging), input=str(target)) for value in settings.get("launch_command", [])]
        launch_marker = self.work / "filmlab-launched.flag"
        if launch and not launch_marker.exists():
            subprocess.Popen(launch, cwd=staging)  # noqa: S603 - command is explicit local config
            launch_marker.write_text(utc_now() + "\n", encoding="ascii")
            self.event("launched configured FilmLab batch command", group_id=group_id)

    def import_positive(self, group_id: str) -> None:
        if self.group_status(group_id) not in {"awaiting_positive", "positive_verified", "approved"}:
            return
        staging = self.db.execute(
            "SELECT path FROM outputs WHERE group_id=? AND kind='filmlab_staging'", (group_id,)
        ).fetchone()
        if not staging:
            return
        stem = Path(staging["path"]).stem.lower()
        extensions = {value.lower() for value in self.config.get("filmlab", {}).get("positive_extensions", [])}
        matches = sorted(
            path for path in self.paths["positive_inbox"].glob("*")
            if path.is_file() and path.suffix.lower() in extensions and path.stem.lower() == stem
        )
        if not matches:
            return
        source = matches[-1]
        self.wait_stable([source], 30)
        target_dir = self.paths["positives"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        source_hash = sha256_file(source)
        if not target.exists() or target.stat().st_size != source.stat().st_size or sha256_file(target) != source_hash:
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        self.record_output(group_id, "positive", target)
        self.make_preview(group_id, target)
        self.set_group(group_id, "positive_verified")

    def make_preview(self, group_id: str, source: Path) -> None:
        settings = self.config.get("previews", {})
        if not settings.get("enabled", True):
            return
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise RuntimeError("Pillow is required for previews; install project dependencies") from exc
        target_dir = self.paths["previews"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{source.stem}.jpg"
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            edge = int(settings.get("max_long_edge", 2400))
            image.thumbnail((edge, edge))
            temporary = target.with_suffix(".jpg.tmp")
            image.save(temporary, format="JPEG", quality=int(settings.get("jpeg_quality", 88)), optimize=True)
            os.replace(temporary, target)
        self.record_output(group_id, "preview", target)

    def process_once(self) -> None:
        self.check_environment()
        stable = self.discover()
        if stable:
            self.event(f"reading PixelShift metadata from {len(stable)} stable raw file(s)")
            self.read_metadata(stable)
        groups = self.complete_groups()
        if not groups:
            self.event("no complete stable PS16 groups ready")
            return
        self.event(f"found {len(groups)} complete stable PS16 group(s)")
        if self.dry_run:
            for group_id in groups:
                source = self.expected_dng(group_id)
                if source.is_file():
                    self.event(f"DRY RUN would verify existing {source.name}", group_id=group_id)
                else:
                    self.event(f"DRY RUN would create PixelShift DNG {source.name}", group_id=group_id)
                for name, profile in self.config["jpeg_xl_profiles"].items():
                    if profile.get("enabled", True):
                        self.event(
                            f"DRY RUN would encode profile {name} at {profile['level']}", group_id=group_id
                        )
                if self.config.get("filmlab", {}).get("enabled"):
                    self.event("DRY RUN would create ASCII-safe FilmLab staging", group_id=group_id)
            return
        self.check_free_space()
        pending_dng = [g for g in groups if self.group_status(g) in {"discovered", "error"}]
        if pending_dng:
            try:
                self.ensure_source_dngs(pending_dng)
            except Exception as exc:
                for group_id in pending_dng:
                    self.mark_error(group_id, exc)
        for group_id in groups:
            try:
                status = self.group_status(group_id)
                if status == "dng_verified":
                    self.ensure_profiles(group_id)
                    status = self.group_status(group_id)
                if status == "profiles_verified":
                    self.stage_filmlab(group_id)
                self.import_positive(group_id)
            except Exception as exc:
                self.mark_error(group_id, exc)

    def mark_error(self, group_id: str, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        self.set_group(group_id, "error", error=message)
        if not self.dry_run:
            self.paths["errors"].mkdir(parents=True, exist_ok=True)
            atomic_json(self.paths["errors"] / f"{ascii_name(group_id)}.json", {
                "at": utc_now(), "group_id": group_id, "error": message,
                "raw_files": [str(path) for path in self.group_files(group_id)],
            })
        self.event(message, group_id=group_id, level="ERROR")

    def status(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT g.group_id,g.status,g.error,g.approved_at,COUNT(o.kind) AS outputs "
            "FROM groups g LEFT JOIN outputs o ON o.group_id=g.group_id GROUP BY g.group_id ORDER BY g.group_id"
        ).fetchall()
        result = [dict(row) for row in rows]
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    def retry(self, group_id: str) -> None:
        row = self.db.execute("SELECT status FROM groups WHERE group_id=?", (group_id,)).fetchone()
        if not row:
            raise KeyError(f"unknown group: {group_id}")
        self.db.execute(
            "UPDATE groups SET status='discovered',error=NULL,attempts=attempts+1,updated_at=? WHERE group_id=?",
            (utc_now(), group_id),
        )
        self.db.commit()
        self.event("reset for retry", group_id=group_id)

    def approve(self, group_id: str) -> None:
        status = self.group_status(group_id)
        require_positive = self.config.get("cleanup", {}).get("require_positive", True)
        allowed = {"positive_verified"} if require_positive else {"verified", "awaiting_positive", "positive_verified"}
        if status not in allowed:
            raise RuntimeError(f"group {group_id} is {status}; approval requires {sorted(allowed)}")
        self.assert_cleanup_outputs(group_id)
        self.assert_raw_integrity(group_id, allow_quarantine=False, create_hashes=True)
        self.db.execute("UPDATE groups SET status='approved',approved_at=?,updated_at=? WHERE group_id=?",
                        (utc_now(), utc_now(), group_id))
        self.db.commit()
        self.event("explicitly approved for retention cleanup", group_id=group_id)

    def retention_limit(self) -> int:
        return int(self.config.get("cleanup", {}).get("retention_groups", 2))

    def cleanup_mode(self) -> str:
        return str(self.config.get("cleanup", {}).get("prune_mode", "move"))

    def assert_cleanup_outputs(self, group_id: str) -> None:
        required_kinds = ["source_dng"]
        required_kinds.extend(
            f"jxl:{name}" for name, item in self.config["jpeg_xl_profiles"].items()
            if item.get("enabled", True) and item.get("required_for_cleanup")
        )
        if self.config.get("cleanup", {}).get("require_positive", True):
            required_kinds.append("positive")
        for kind in required_kinds:
            row = self.db.execute(
                "SELECT path,size,sha256 FROM outputs WHERE group_id=? AND kind=?", (group_id, kind)
            ).fetchone()
            if not row:
                raise RuntimeError(f"required verified output is missing from queue: {kind}")
            path = Path(row["path"])
            if not path.is_file() or path.stat().st_size != row["size"] or sha256_file(path) != row["sha256"]:
                raise RuntimeError(f"required output no longer matches verified record: {kind}: {path}")

    def assert_raw_integrity(
        self, group_id: str, *, allow_quarantine: bool, create_hashes: bool = False
    ) -> None:
        rows = self.db.execute(
            "SELECT path,size,sha256 FROM raw_files WHERE group_id=? ORDER BY shot,path", (group_id,)
        ).fetchall()
        if len(rows) != 16:
            raise RuntimeError(f"raw integrity requires 16 queue records, found {len(rows)}")
        target_dir = self.paths["quarantine"] / ascii_name(group_id)
        for row in rows:
            source = Path(row["path"])
            target = target_dir / source.name
            present = [path for path in (source, target) if path.is_file()]
            if not allow_quarantine and target.is_file():
                raise RuntimeError(f"raw is already present in quarantine before approval: {target}")
            if len(present) != 1:
                raise RuntimeError(f"raw must exist in exactly one expected location: {source} / {target}")
            actual = present[0]
            if actual.stat().st_size != row["size"]:
                raise RuntimeError(f"raw size changed: {actual}")
            digest = sha256_file(actual)
            if row["sha256"] and digest != row["sha256"]:
                raise RuntimeError(f"raw checksum changed: {actual}")
            if not row["sha256"]:
                if not create_hashes:
                    raise RuntimeError(f"raw checksum was not recorded during approval: {source}")
                self.db.execute("UPDATE raw_files SET sha256=? WHERE path=?", (digest, str(source)))
        self.db.commit()

    def prune(self, token: str) -> None:
        if not self.config.get("cleanup", {}).get("enabled", False):
            raise RuntimeError("cleanup.enabled is false")
        expected = str(self.config["batch"]["id"])
        if token != expected:
            raise RuntimeError("approval token must exactly equal batch.id")
        limit = self.retention_limit()
        rows = self.db.execute(
            "SELECT group_id,status FROM groups WHERE status IN ('approved','quarantined') "
            "ORDER BY COALESCE(approved_at,updated_at),group_id"
        ).fetchall()
        if not rows:
            raise RuntimeError("no approved or quarantined groups to prune")
        if len(rows) <= limit:
            self.event(f"cleanup retention window keeps {len(rows)} group(s); nothing to prune")
            return
        root = self.paths["quarantine"].resolve()
        doomed = rows[:-limit] if limit else rows
        for row in doomed:
            group_id = row["group_id"]
            target_dir = (root / ascii_name(group_id)).resolve()
            if root != target_dir and root not in target_dir.parents:
                raise RuntimeError(f"unsafe quarantine target: {target_dir}")
            self.assert_cleanup_outputs(group_id)
            self.assert_raw_integrity(group_id, allow_quarantine=True)
            if self.cleanup_mode() == "move":
                target_dir.mkdir(parents=True, exist_ok=True)
                for source in self.group_files(group_id):
                    if source.exists():
                        target = target_dir / source.name
                        if target.exists():
                            raise RuntimeError(f"both raw source and quarantine target exist: {source} / {target}")
                        shutil.move(str(source), str(target))
                self.assert_raw_integrity(group_id, allow_quarantine=True)
                self.set_group(group_id, "quarantined")
                self.event(
                    f"moved 16 raw exposures to recoverable quarantine {target_dir} "
                    f"(retention window {limit})",
                    group_id=group_id,
                )
            else:
                raw_rows = self.db.execute(
                    "SELECT path FROM raw_files WHERE group_id=? ORDER BY shot,path", (group_id,)
                ).fetchall()
                for raw_row in raw_rows:
                    source = Path(raw_row["path"])
                    target = target_dir / source.name
                    present = [path for path in (source, target) if path.is_file()]
                    if len(present) != 1:
                        raise RuntimeError(
                            f"raw must exist in exactly one expected location before deletion: {source} / {target}"
                        )
                    present[0].unlink()
                cleaned_at = utc_now()
                self.db.execute(
                    "UPDATE groups SET status='cleaned',error=NULL,cleaned_at=?,updated_at=? WHERE group_id=?",
                    (cleaned_at, cleaned_at, group_id),
                )
                self.db.commit()
                self.event(
                    f"deleted 16 verified raw exposures outside retention window (retain last {limit})",
                    group_id=group_id,
                )


def parse_pixelshift_info(value: object) -> tuple[str, int, int] | None:
    if not value:
        return None
    match = re.search(r"Group\s+(\d+),\s*Shot\s+(\d+)/(\d+)", str(value), re.IGNORECASE)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def ascii_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return result or "item"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restartable Windows PS16 mass-scan queue")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("command", choices=["watch", "once", "status", "retry", "approve", "prune"])
    parser.add_argument("--group-id")
    parser.add_argument("--approval-token")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config.resolve())
    pipeline = Pipeline(
        config,
        dry_run=args.dry_run,
        exclusive=args.command in {"watch", "once"} and not args.dry_run,
    )
    try:
        if args.command == "status":
            pipeline.status()
        elif args.command == "retry":
            if not args.group_id:
                raise ValueError("retry requires --group-id")
            pipeline.retry(args.group_id)
        elif args.command == "approve":
            if not args.group_id:
                raise ValueError("approve requires --group-id")
            pipeline.approve(args.group_id)
        elif args.command == "prune":
            if not args.approval_token:
                raise ValueError("prune requires --approval-token")
            pipeline.prune(args.approval_token)
        elif args.command == "once":
            pipeline.process_once()
        else:
            interval = max(1, int(config.get("watch", {}).get("poll_seconds", 5)))
            pipeline.event(f"watching {pipeline.paths['incoming']} every {interval}s; Ctrl+C stops safely")
            while True:
                try:
                    pipeline.process_once()
                except Exception as exc:
                    pipeline.event(f"watch cycle failed: {type(exc).__name__}: {exc}", level="ERROR")
                time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped; queue state is saved.")
    finally:
        pipeline.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
