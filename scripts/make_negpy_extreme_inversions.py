from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIEWERS = ROOT / "site/assets/review-viewers"
DEFAULT_DJXL = ROOT / "work/jxl-tools/bin/djxl.exe"
MODE_KEY = "negpy_extreme_inversion"
MODE_LABEL = "NegPy extreme inversion"
MODE_DESCRIPTION = (
    "Runs the real NegPy C-41 or B&W print pipeline on a 16-bit working crop. "
    "Normalization is locked to the PS16 reference; ISO-R 50 and fixed manual "
    "density/grade make this a deliberately hard edit-resilience check."
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def resolve_source(value: object) -> Path:
    if not isinstance(value, dict) or not value.get("path"):
        raise ValueError("viewer metadata has no source path")
    path = Path(str(value["path"]))
    return path if path.is_absolute() else ROOT / path


def output_mapping(metadata: dict[str, Any]) -> dict[str, str]:
    image_sets = metadata.get("images_by_transform")
    if not isinstance(image_sets, dict) or not isinstance(image_sets.get("identity"), dict):
        raise ValueError("viewer metadata has no identity image set")
    mapping: dict[str, str] = {}
    for key, filename in image_sets["identity"].items():
        source_name = Path(str(filename))
        mapping[str(key)] = f"{source_name.stem}_{MODE_KEY}.png"
    return mapping


def mode_for_scan(scan_set: str) -> str:
    return "B&W Negative" if "adox" in scan_set.casefold() else "Color Negative"


def merge_mode(metadata: dict[str, Any], images: dict[str, str], provenance: dict[str, Any]) -> dict[str, Any]:
    result = dict(metadata)
    image_sets = dict(result.get("images_by_transform", {}))
    image_sets[MODE_KEY] = images
    result["images_by_transform"] = image_sets

    modes = [
        dict(item)
        for item in result.get("view_modes", [])
        if isinstance(item, dict) and item.get("key") != MODE_KEY
    ]
    modes.append({"key": MODE_KEY, "label": MODE_LABEL, "description": MODE_DESCRIPTION})
    result["view_modes"] = modes
    result[MODE_KEY] = provenance
    return result


def _ppm_tokens(handle: Any, count: int) -> list[bytes]:
    tokens: list[bytes] = []
    token = bytearray()
    while len(tokens) < count:
        value = handle.read(1)
        if not value:
            raise ValueError("truncated PPM header")
        if value == b"#" and not token:
            handle.readline()
            continue
        if value.isspace():
            if token:
                tokens.append(bytes(token))
                token.clear()
            continue
        token.extend(value)
    return tokens


def ppm_memmap(path: Path) -> tuple[np.memmap, int]:
    with path.open("rb") as handle:
        magic, width_raw, height_raw, max_raw = _ppm_tokens(handle, 4)
        offset = handle.tell()
    if magic != b"P6":
        raise ValueError(f"expected binary RGB PPM, got {magic!r}: {path}")
    width, height, maximum = int(width_raw), int(height_raw), int(max_raw)
    if width <= 0 or height <= 0 or maximum not in (255, 65535):
        raise ValueError(f"unsupported PPM header: {width}x{height}, max={maximum}")
    dtype = np.uint8 if maximum == 255 else np.dtype(">u2")
    expected = offset + width * height * 3 * np.dtype(dtype).itemsize
    if path.stat().st_size < expected:
        raise ValueError(f"truncated PPM pixel data: {path}")
    return np.memmap(path, dtype=dtype, mode="r", offset=offset, shape=(height, width, 3)), maximum


def crop_array(array: np.ndarray, crop: Iterable[object]) -> np.ndarray:
    x, y, width, height = (int(value) for value in crop)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"invalid crop: {(x, y, width, height)}")
    if x + width > array.shape[1] or y + height > array.shape[0]:
        raise ValueError(f"crop {(x, y, width, height)} exceeds source shape {array.shape}")
    return np.ascontiguousarray(array[y : y + height, x : x + width, :3])


def crop_to_uint16(crop: np.ndarray) -> np.ndarray:
    if crop.dtype.kind == "u" and crop.dtype.itemsize == 1:
        return crop.astype(np.uint16) * np.uint16(257)
    if crop.dtype.kind == "u" and crop.dtype.itemsize == 2:
        return crop.astype(np.uint16)
    raise ValueError(f"unsupported crop dtype: {crop.dtype}")


def tiff_icc(path: Path, tifffile: Any) -> bytes | None:
    with tifffile.TiffFile(path) as tif:
        tag = tif.pages[0].tags.get("InterColorProfile")
        return bytes(tag.value) if tag is not None else None


def tiff_memmap(path: Path, tifffile: Any) -> tuple[np.ndarray, bytes | None]:
    try:
        array = tifffile.memmap(path)
    except Exception as exc:
        raise RuntimeError(f"source TIFF is not memory-mappable; refusing a full-frame read: {path}") from exc
    if array.ndim != 3 or array.shape[2] < 3 or array.dtype not in (np.uint8, np.uint16):
        raise ValueError(f"unsupported source TIFF shape/dtype: {array.shape} {array.dtype}: {path}")
    return array, tiff_icc(path, tifffile)


def negpy_revision(root: Path) -> tuple[str, bool]:
    common = ["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root)]
    revision = subprocess.run(
        [*common, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            [*common, "status", "--porcelain"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    return revision, dirty


def load_negpy(root: Path, user_dir: Path) -> dict[str, Any]:
    os.environ["NEGPY_USER_DIR"] = str(user_dir)
    sys.path.insert(0, str(root))
    from negpy.domain.models import ColorSpace, ExportFormat, ExportResolutionMode, WorkspaceConfig
    from negpy.features.exposure.normalization import analyze_log_exposure_bounds
    from negpy.features.process.models import ProcessMode
    from negpy.kernel.system.config import APP_CONFIG
    from negpy.services.rendering.image_processor import ImageProcessor

    APP_CONFIG.use_gpu = False
    return {
        "ColorSpace": ColorSpace,
        "ExportFormat": ExportFormat,
        "ExportResolutionMode": ExportResolutionMode,
        "WorkspaceConfig": WorkspaceConfig,
        "ProcessMode": ProcessMode,
        "ImageProcessor": ImageProcessor,
        "analyze_log_exposure_bounds": analyze_log_exposure_bounds,
    }


def negpy_config(api: dict[str, Any], process_mode: str) -> Any:
    config = api["WorkspaceConfig"]()
    process = replace(
        config.process,
        process_mode=api["ProcessMode"](process_mode),
        analysis_buffer=0.0,
        luma_range_clip=1.0,
        color_range_clip=5.0,
        lock_bounds=False,
        local_floors=(0.0, 0.0, 0.0),
        local_ceils=(0.0, 0.0, 0.0),
    )
    exposure = replace(
        config.exposure,
        density=1.0,
        grade=50.0,
        auto_exposure=False,
        auto_normalize_contrast=False,
        cast_removal_strength=0.0,
        toe=-1.0,
        shoulder=-1.0,
    )
    export = replace(
        config.export,
        export_fmt=api["ExportFormat"].PNG,
        export_bit_depth=16,
        export_resolution_mode=api["ExportResolutionMode"].ORIGINAL,
        export_color_space=api["ColorSpace"].SRGB.value,
    )
    return replace(config, process=process, exposure=exposure, export=export)


def locked_config(config: Any, bounds: Any) -> Any:
    process = replace(
        config.process,
        local_floors=tuple(float(value) for value in bounds.floors),
        local_ceils=tuple(float(value) for value in bounds.ceils),
        lock_bounds=True,
    )
    return replace(config, process=process)


def write_crop_tiff(path: Path, crop: np.ndarray, profile: bytes | None, tifffile: Any) -> None:
    kwargs: dict[str, Any] = {"photometric": "rgb", "compression": "zlib", "predictor": True}
    if profile:
        kwargs["iccprofile"] = profile
    tifffile.imwrite(path, crop, **kwargs)


def render_crop(
    crop: np.ndarray,
    profile: bytes | None,
    output: Path,
    config: Any,
    api: dict[str, Any],
    tifffile: Any,
    work_dir: Path,
) -> None:
    input_path = work_dir / "negpy-input.tif"
    write_crop_tiff(input_path, crop, profile, tifffile)
    processor = api["ImageProcessor"]()
    encoded, status = processor.process_export(
        str(input_path),
        config,
        config.export,
        sha256(input_path),
        prefer_gpu=False,
    )
    if encoded is None:
        raise RuntimeError(f"NegPy export failed: {status}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    input_path.unlink()


def measure_reference_bounds(
    crop: np.ndarray,
    profile: bytes | None,
    config: Any,
    api: dict[str, Any],
    tifffile: Any,
    work_dir: Path,
) -> Any:
    input_path = work_dir / "negpy-meter-input.tif"
    write_crop_tiff(input_path, crop, profile, tifffile)
    processor = api["ImageProcessor"]()
    linear, _ir, _color_space = processor._load_source_f32(str(input_path), config)
    bounds = api["analyze_log_exposure_bounds"](
        linear,
        analysis_buffer=config.process.analysis_buffer,
        process_mode=config.process.process_mode,
        e6_normalize=config.process.e6_normalize,
        percentile_clip=config.process.luma_range_clip,
        color_clip=config.process.color_range_clip,
    )
    input_path.unlink()
    return bounds


def discover_viewers(root: Path, cases: set[str]) -> list[dict[str, Any]]:
    viewers: list[dict[str, Any]] = []
    for metadata_path in sorted(root.rglob("metadata.json")):
        metadata = read_json(metadata_path)
        case_key = f"{metadata.get('scan_set', '')}|{metadata.get('set_id', '')}"
        if cases and case_key not in cases:
            continue
        crop = metadata.get("crop")
        sources = metadata.get("build_inputs", {}).get("sources", {})
        if not isinstance(crop, list) or len(crop) != 4 or not isinstance(sources, dict):
            continue
        viewers.append(
            {
                "metadata_path": metadata_path,
                "directory": metadata_path.parent,
                "metadata": metadata,
                "scan_set": str(metadata.get("scan_set", "")),
                "set_id": str(metadata.get("set_id", "")),
                "crop_name": str(metadata.get("crop_name", "")),
                "crop": crop,
                "sources": sources,
                "outputs": output_mapping(metadata),
            }
        )
    return viewers


def decode_jxl(djxl: Path, source: Path, output: Path) -> None:
    def tool_path(path: Path) -> str:
        if os.name != "nt" and djxl.suffix.casefold() == ".exe":
            return subprocess.run(
                ["wslpath", "-w", str(path)], check=True, capture_output=True, text=True
            ).stdout.strip()
        return str(path)

    subprocess.run(
        [str(djxl), tool_path(source), tool_path(output), "--bits_per_sample=16", "--num_threads=4", "--quiet"],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a real NegPy extreme-inversion mode to the existing review crops."
    )
    parser.add_argument("--negpy-root", type=Path, required=True)
    parser.add_argument("--expected-negpy-revision")
    parser.add_argument("--viewers", type=Path, default=DEFAULT_VIEWERS)
    parser.add_argument("--djxl", type=Path, default=DEFAULT_DJXL)
    parser.add_argument("--case", action="append", default=[], help='limit to "scan set|set id"')
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    negpy_root = args.negpy_root.resolve()
    revision, dirty = negpy_revision(negpy_root)
    if dirty:
        raise SystemExit(f"NegPy worktree must be clean: {negpy_root}")
    if args.expected_negpy_revision and revision != args.expected_negpy_revision:
        raise SystemExit(f"NegPy revision mismatch: expected {args.expected_negpy_revision}, got {revision}")
    if not args.djxl.is_file():
        raise SystemExit(f"djxl not found: {args.djxl}")

    viewers = discover_viewers(args.viewers, set(args.case))
    if not viewers:
        raise SystemExit("no matching viewer metadata found")

    try:
        import tifffile
    except ModuleNotFoundError as exc:
        raise SystemExit("tifffile is required") from exc

    temp_root = ROOT / "work"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="negpy-extreme-", dir=temp_root) as temporary:
        work_dir = Path(temporary)
        api = load_negpy(negpy_root, work_dir / "user")
        locked: dict[Path, Any] = {}
        generated: dict[Path, list[dict[str, Any]]] = {item["metadata_path"]: [] for item in viewers}

        for index, item in enumerate(viewers, start=1):
            reference_path = resolve_source(item["sources"].get("ps16"))
            raw_path = resolve_source(item["sources"].get("raw61_registered"))
            print(f"[{index}/{len(viewers)}] {item['scan_set']} / {item['set_id']} / {item['crop_name']}", flush=True)
            reference, reference_icc = tiff_memmap(reference_path, tifffile)
            reference_crop = crop_to_uint16(crop_array(reference, item["crop"]))
            base_config = negpy_config(api, mode_for_scan(item["scan_set"]))
            reference_output = item["directory"] / item["outputs"]["reference"]
            bounds = measure_reference_bounds(
                reference_crop,
                reference_icc,
                base_config,
                api,
                tifffile,
                work_dir,
            )
            locked[item["metadata_path"]] = locked_config(base_config, bounds)
            if args.force or not reference_output.is_file():
                render_crop(
                    reference_crop,
                    reference_icc,
                    reference_output,
                    locked[item["metadata_path"]],
                    api,
                    tifffile,
                    work_dir,
                )
            generated[item["metadata_path"]].append(
                {"key": "reference", "source": str(reference_path.relative_to(ROOT)), "sha256": sha256(reference_output)}
            )
            del reference_crop, reference

            raw, raw_icc = tiff_memmap(raw_path, tifffile)
            raw_crop = crop_to_uint16(crop_array(raw, item["crop"]))
            raw_output = item["directory"] / item["outputs"]["raw61"]
            if args.force or not raw_output.is_file():
                render_crop(raw_crop, raw_icc, raw_output, locked[item["metadata_path"]], api, tifffile, work_dir)
            generated[item["metadata_path"]].append(
                {"key": "raw61", "source": str(raw_path.relative_to(ROOT)), "sha256": sha256(raw_output)}
            )
            del raw_crop, raw

        jobs: dict[Path, list[tuple[dict[str, Any], str]]] = {}
        for item in viewers:
            jxl_sources = item["sources"].get("jxl", {})
            if not isinstance(jxl_sources, dict):
                continue
            for key in item["outputs"]:
                if not key.startswith("jxl_"):
                    continue
                level = key.removeprefix("jxl_")
                state = jxl_sources.get(level)
                if isinstance(state, dict) and state.get("path"):
                    jobs.setdefault(resolve_source(state), []).append((item, key))

        for index, (source, source_jobs) in enumerate(sorted(jobs.items()), start=1):
            pending: list[tuple[dict[str, Any], str]] = []
            for item, key in source_jobs:
                output = item["directory"] / item["outputs"][key]
                if args.force or not output.is_file():
                    pending.append((item, key))
                else:
                    generated[item["metadata_path"]].append(
                        {"key": key, "source": str(source.relative_to(ROOT)), "sha256": sha256(output)}
                    )
            if not pending:
                continue
            free = shutil.disk_usage(work_dir).free
            if free < 4 * 1024**3:
                raise RuntimeError("less than 4 GiB is free for the temporary JXL decode")
            decoded = work_dir / "decoded.ppm"
            print(f"[JXL {index}/{len(jobs)}] {source.relative_to(ROOT)}", flush=True)
            decode_jxl(args.djxl, source, decoded)
            pixels, _maximum = ppm_memmap(decoded)
            profile_source = resolve_source(source_jobs[0][0]["sources"].get("ps16"))
            profile = tiff_icc(profile_source, tifffile)
            for item, key in pending:
                output = item["directory"] / item["outputs"][key]
                crop = crop_to_uint16(crop_array(pixels, item["crop"]))
                render_crop(crop, profile, output, locked[item["metadata_path"]], api, tifffile, work_dir)
                del crop
                generated[item["metadata_path"]].append(
                    {"key": key, "source": str(source.relative_to(ROOT)), "sha256": sha256(output)}
                )
            del pixels
            decoded.unlink()

        for item in viewers:
            provenance = {
                "generator": str(Path(__file__).relative_to(ROOT)),
                "negpy_revision": revision,
                "negpy_worktree_clean": True,
                "input_precision": "native source precision promoted to a 16-bit working container",
                "crop_size": item["crop"][2:],
                "process_mode": mode_for_scan(item["scan_set"]),
                "normalization": "PS16 reference bounds locked across RAW61 and JXL candidates",
                "settings": {
                    "iso_r_grade": 50.0,
                    "print_density": 1.0,
                    "luma_range_clip_percent": 1.0,
                    "color_clip_percent": 5.0,
                    "auto_density": False,
                    "auto_grade": False,
                    "cast_removal_strength": 0.0,
                    "toe": -1.0,
                    "shoulder": -1.0,
                    "output": "16-bit sRGB PNG",
                },
                "outputs": generated[item["metadata_path"]],
            }
            metadata = merge_mode(item["metadata"], item["outputs"], provenance)
            item["metadata_path"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Added {MODE_LABEL} to {len(viewers)} viewer crop(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
