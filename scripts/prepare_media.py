#!/usr/bin/env python3
"""Publish frozen showcase media through verified stream-copy remuxing only.

Requires ffmpeg and ffprobe. Source files and experiment records are read-only.
Absolute source paths appear only in the private preparation report.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import tempfile


ROLES = ["source", "proxy", "without-proxy", "with-proxy"]
BRANCHES = {
    "without-proxy": "source_plus_prompt",
    "with-proxy": "source_plus_edited_proxy_plus_prompt",
}
EXPERIMENT = {
    "id": "openve_h3_int8_early_step_20261031",
    "steps": 20,
    "proxy_steps": 5,
    "seed": 42,
    "fps": 24,
}
SOURCE_COLLECTION = "openve-h3-int8-early-step-20261031"
STREAM_FIELDS = [
    "index", "codec_type", "codec_name", "profile", "codec_tag_string",
    "width", "height", "pix_fmt", "r_frame_rate", "avg_frame_rate",
    "duration", "nb_frames", "sample_rate", "channels", "channel_layout",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    return json.loads(run("ffprobe", "-v", "error", "-show_streams",
                          "-show_format", "-of", "json", str(path)))


def normalized_relative(value: str) -> str:
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts and "\\" not in value,
            f"Unsafe relative source path: {value}")
    require(path.parts[0] == "assets-int8-early-v1", "Unexpected source collection")
    return path.as_posix()


def video_metadata(metadata: dict, frames: int, geometry=(960, 544), fps=24) -> dict:
    videos = [s for s in metadata["streams"] if s["codec_type"] == "video"]
    require(len(videos) == 1, "Expected exactly one video stream")
    video = videos[0]
    require((video.get("width"), video.get("height")) == tuple(geometry),
            "Video geometry differs from the frozen source; refusing to transcode")
    require(Fraction(video["avg_frame_rate"]) == fps, "Video average FPS differs from its frozen source")
    require(Fraction(video["r_frame_rate"]) == fps, "Video nominal FPS differs from its frozen source")
    require(int(video["nb_frames"]) == frames, "Frame count differs from case metadata")
    require(video["codec_name"] == "h264", "Unexpected browser video codec; refusing to transcode")
    for stream in metadata["streams"]:
        require(stream["codec_type"] in {"video", "audio"}, "Unexpected stream type")
        if stream["codec_type"] == "audio":
            require(stream["codec_name"] == "aac", "Unexpected audio codec; refusing to transcode")
    return video


def stream_hashes(path: Path) -> list[dict]:
    output = run("ffmpeg", "-v", "error", "-threads", "1", "-i", str(path),
                 "-map", "0", "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-")
    rows = []
    for line in output.splitlines():
        match = re.fullmatch(r"(\d+),([a-z]),SHA256=([0-9a-f]{64})", line)
        require(match is not None, f"Unexpected stream hash output: {line}")
        rows.append({"index": int(match[1]), "type": match[2], "sha256": match[3]})
    require(bool(rows), "No stream hashes produced")
    return rows


def video_packet_hash(path: Path) -> str:
    output = run("ffmpeg", "-v", "error", "-threads", "1", "-i", str(path),
                 "-map", "0:v:0", "-c", "copy", "-f", "hash", "-hash", "sha256", "-")
    match = re.fullmatch(r"SHA256=([0-9a-f]{64})\s*", output)
    require(match is not None, "Unexpected video packet hash output")
    return match[1]


def faststart(path: Path) -> bool:
    positions = {}
    with path.open("rb") as stream:
        total = path.stat().st_size
        offset = 0
        while offset + 8 <= total:
            stream.seek(offset)
            size, box = struct.unpack(">I4s", stream.read(8))
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0]
            elif size == 0:
                size = total - offset
            require(size >= 8 and offset + size <= total, "Invalid MP4 box boundaries")
            positions.setdefault(box, offset)
            offset += size
    return b"moov" in positions and b"mdat" in positions and positions[b"moov"] < positions[b"mdat"]


def check_conditioning(case: dict, site: Path, experiment_root: Path) -> tuple[dict, list[dict]]:
    case_id = case["id"]
    records = {}
    private_refs = []
    original_source_hash = None
    for role, branch in BRANCHES.items():
        root = experiment_root / "outputs" / case_id / "h3" / branch
        record_path = root / "raw.conditioning.json"
        record = json.loads(record_path.read_text())
        require(record["seed"] == 42 and record["steps"] == 20, f"{case_id}: sampling mismatch")
        require(record["source_condition_steps"] == list(range(1, 21)), "Source conditioning mismatch")
        require(record["model_files"]["diffusion_models"] ==
                "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "Wrong H3 model")
        expected_proxy = list(range(1, 6)) if role == "with-proxy" else []
        require(record["proxy_condition_steps"] == expected_proxy, "Proxy conditioning mismatch")
        require(record["early_step"] is (role == "with-proxy"), "Early-step flag mismatch")
        for ref in record["references"]:
            ref_path = Path(ref["path"])
            require(sha256(ref_path) == ref["sha256"], "Frozen conditioning reference hash mismatch")
            private_refs.append({"case_id": case_id, "role": role, "path": str(ref_path),
                                 "sha256": ref["sha256"]})
        source_hash = record["references"][0]["sha256"]
        if original_source_hash is None:
            original_source_hash = source_hash
        require(source_hash == original_source_hash, "Both arms must share their source reference")
        if role == "with-proxy":
            require((site / case["media"][1]["raw"]).samefile(record["references"][1]["path"]),
                    "Proxy display is not paired with the frozen experiment proxy input")
            audit = record["actual_sampling_audit"]
            require((audit["seed"], audit["steps"], audit["keep_steps"]) == (42, 20, 5),
                    "Recorded sampling audit settings mismatch")
            require(len(audit["trace"]) == 20, "Incomplete sampling trace")
            for index, step in enumerate(audit["trace"], start=1):
                require(step["step"] == index, "Sampling trace step order mismatch")
                expected = ("full", 2) if index <= 5 else ("base", 1)
                require((step["branch"], step["reference_count"]) == expected,
                        "Sampling trace is not the accepted early-step schedule")
        records[role] = {
            "record": f"outputs/{case_id}/h3/{branch}/raw.conditioning.json",
            "record_sha256": sha256(record_path),
            "seed": 42, "steps": 20,
            "source_condition_steps": list(range(1, 21)),
            "proxy_condition_steps": expected_proxy,
            "actual_sampling_trace_verified": role == "with-proxy",
        }
    return records, private_refs


def prepare_one(task: dict, dist: Path, temporary_root: Path) -> dict:
    source = task["source"]
    geometry = tuple(task.get("geometry", (960, 544)))
    fps = task.get("fps", 24)
    require(sha256(source) == task["source_sha256"], "Frozen source changed after preflight")
    source_probe = probe(source)
    video_metadata(source_probe, task["frames"], geometry, fps)
    before_stream_hashes = stream_hashes(source)
    before_video_hash = video_packet_hash(source)
    prefix = f"{task['case_id']}-{task['role']}"
    temporary_video = temporary_root / f"{prefix}.mp4"
    temporary_poster = temporary_root / f"{prefix}.jpg"
    already_faststart = faststart(source)
    if already_faststart:
        shutil.copyfile(source, temporary_video)
    else:
        run("ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-i", str(source),
            "-map", "0", "-c", "copy", "-map_metadata", "0", "-map_chapters", "0",
            "-movflags", "+faststart", "-y", str(temporary_video))
    after_probe = probe(temporary_video)
    video = video_metadata(after_probe, task["frames"], geometry, fps)
    before_streams = [{key: stream.get(key) for key in STREAM_FIELDS}
                      for stream in source_probe["streams"]]
    after_streams = [{key: stream.get(key) for key in STREAM_FIELDS}
                     for stream in after_probe["streams"]]
    require(before_streams == after_streams, "Stream metadata changed during remux")
    after_stream_hashes = stream_hashes(temporary_video)
    after_video_hash = video_packet_hash(temporary_video)
    require(before_stream_hashes == after_stream_hashes, "Encoded audio/video stream hashes changed")
    require(before_video_hash == after_video_hash, "Encoded video packet hash changed")
    require(faststart(temporary_video), "Remuxed MP4 does not have moov before mdat")
    run("ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-ss",
        f"{task['poster_time_seconds']:.9f}", "-i", str(temporary_video), "-map", "0:v:0",
        "-frames:v", "1", "-an", "-q:v", "2", "-threads", "1", "-y", str(temporary_poster))
    poster_stream = probe(temporary_poster)["streams"][0]
    require((poster_stream["width"], poster_stream["height"]) == geometry, "Poster dimensions mismatch")
    require(sha256(source) == task["source_sha256"], "Frozen source changed during preparation")
    video_path = dist / task["src"]
    poster_path = dist / task["poster"]
    video_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_video.replace(video_path)
    temporary_poster.replace(poster_path)
    public = {
        "role": task["role"], "src": task["src"], "source_site_relative_path": task["source_relative"],
        "source_file_sha256": task["source_sha256"], "published_file_sha256": sha256(video_path),
        "source_video_packet_sha256": before_video_hash, "published_video_packet_sha256": after_video_hash,
        "encoded_stream_hashes": after_stream_hashes,
        "source_bytes": source.stat().st_size, "bytes": video_path.stat().st_size,
        "width": video["width"], "height": video["height"], "fps": fps,
        "frames": int(video["nb_frames"]), "duration_seconds": float(video["duration"]),
        "streams": after_streams, "faststart": True, "all_encoded_streams_preserved": True,
        "container_operation": "byte-identical copy" if already_faststart else "stream-copy remux",
        "poster": {"src": task["poster"], "sha256": sha256(poster_path),
                   "bytes": poster_path.stat().st_size, "time_seconds": task["poster_time_seconds"]},
    }
    if task.get("experiment_identity"):
        public["frozen_experiment_identity"] = task["experiment_identity"]
    return {"public": public, "private": {
        "case_id": task["case_id"], "role": task["role"], "source": str(source),
        "resolved_source": str(source.resolve()), "published": str(video_path),
        "source_sha256": task["source_sha256"], "source_stable_during_preparation": True,
    }}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-site", type=Path, required=True)
    parser.add_argument("--experiment-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path,
                        default=Path(__file__).resolve().parents[1] / "content.json")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "dist")
    parser.add_argument("--report-dir", type=Path,
                        default=Path(__file__).resolve().parents[2] / ".code-guided-prep" / "media")
    parser.add_argument("--workers", type=int, choices=[2, 3, 4], default=2)
    args = parser.parse_args()
    site, experiment_root, dist, report_dir = (
        path.resolve() for path in [args.source_site, args.experiment_root, args.output_dir, args.report_dir])
    require(shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None,
            "ffmpeg and ffprobe are required")
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "workers": args.workers,
              "source_site": str(site), "experiment_root": str(experiment_root),
              "output_dir": str(dist), "errors": [], "assets": [], "conditioning_references": []}
    try:
        source_data_path = site / "data.json"
        source_data_sha256 = sha256(source_data_path)
        data = json.loads(source_data_path.read_text())
        require(data["experiment_id"] == SOURCE_COLLECTION and data["prompt_version"] == "early-step",
                "Source data is not the selected early-step run")
        require(data["method"]["early_step"] is True, "Source collection is not early-step")
        cases = {case["id"]: case for case in data["cases"]}
        selection = json.loads(args.selection.read_text())
        case_groups = {category["id"]: [case["id"] for case in category["cases"]]
                       for category in selection["categories"]}
        require(len(case_groups) == 8, "Expected all eight task categories")
        require(all(len(ids) <= 2 for ids in case_groups.values()), "At most two reviewed cases per task")
        selected_ids = [cid for ids in case_groups.values() for cid in ids]
        require(bool(selected_ids) and len(selected_ids) == len(set(selected_ids)), "Empty or duplicate selection")
        tasks = []
        manifest = {"experiment": EXPERIMENT, "cases": {}}
        provenance = {"schema_version": 1, "experiment": EXPERIMENT,
                      "source_collection": SOURCE_COLLECTION, "source_data_sha256": source_data_sha256,
                      "preparation": {"operation": "Copy faststart sources unchanged; otherwise MP4 stream-copy remux",
                                      "video_reencoded": False, "audio_reencoded": False,
                                      "all_streams_mapped": True,
                                      "poster_policy": "One JPEG near 30% of each case; same case timestamp for all four tracks"},
                      "cases": {}}
        for category, case_ids in case_groups.items():
            for case_id in case_ids:
                case = cases[case_id]
                require(case["category"] == category, f"{case_id}: category mismatch")
                frame_count = int(case["frames"])
                duration = frame_count / 24
                require(abs(case["duration"] - duration) < 1e-9, "Case duration does not match frame count")
                poster_frame = round((frame_count - 1) * 0.30)
                poster_time = poster_frame / 24
                conditioning, references = check_conditioning(case, site, experiment_root)
                report["conditioning_references"].extend(references)
                manifest_case = {"duration": duration, "frames": frame_count, "media": []}
                provenance["cases"][case_id] = {
                    "category": category, "duration_seconds": duration, "frames": frame_count,
                    "poster_frame": poster_frame, "poster_time_seconds": poster_time,
                    "conditioning_validation": conditioning, "media": []}
                manifest["cases"][case_id] = manifest_case
                for role, media in zip(ROLES, case["media"][:4]):
                    relative = normalized_relative(media["video"])
                    source = site / relative
                    require(source.is_file(), f"Missing {case_id} {role} source")
                    source_sha256 = sha256(source)
                    identity = None
                    if role in BRANCHES:
                        require(media["experiment_version"] == "early-step", "Legacy output encountered")
                        relative_output = f"outputs/{case_id}/h3/{BRANCHES[role]}/display.mp4"
                        experiment_output = experiment_root / relative_output
                        require(experiment_output.is_file(), "Frozen experiment display is missing")
                        require(sha256(experiment_output) == source_sha256,
                                "Source-site output differs from frozen current experiment output")
                        identity = {"relative_path": relative_output, "sha256": source_sha256,
                                    "matches_source_site": True}
                    video_path = f"assets/cases/{case_id}/{role}.mp4"
                    poster_path = f"assets/cases/{case_id}/{role}.jpg"
                    manifest_case["media"].append({"role": role, "src": video_path, "poster": poster_path})
                    tasks.append({"case_id": case_id, "role": role, "source": source,
                                  "source_relative": relative, "source_sha256": source_sha256,
                                  "experiment_identity": identity, "frames": frame_count,
                                  "poster_time_seconds": poster_time, "src": video_path, "poster": poster_path})
        with tempfile.TemporaryDirectory(prefix="remux-", dir=report_dir) as temporary:
            results = {}
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending = {pool.submit(prepare_one, task, dist, Path(temporary)): task for task in tasks}
                for future in as_completed(pending):
                    task = pending[future]
                    try:
                        result = future.result()
                        results[(task["case_id"], task["role"])] = result
                        report["assets"].append(result["private"])
                        print(f"Verified {task['case_id']} {task['role']}", flush=True)
                    except Exception as error:
                        report["errors"].append({"case_id": task["case_id"], "role": task["role"],
                                                 "error": str(error)})
            require(not report["errors"], "Media preparation failed; consult private report")
        require(sha256(source_data_path) == source_data_sha256, "Source data changed during preparation")
        for task in tasks:
            public = results[(task["case_id"], task["role"])]["public"]
            provenance["cases"][task["case_id"]]["media"].append(public)
        assets = [result["public"] for result in results.values()]
        largest = max(assets, key=lambda item: item["bytes"])
        validation = {
            "case_count": len(manifest["cases"]), "video_count": len(assets), "poster_count": len(assets),
            "all_geometry_960x544": True, "all_fps_24": True, "all_frame_counts_match": True,
            "all_stream_metadata_preserved": True, "all_video_packet_hashes_match": True,
            "all_audio_video_stream_hashes_match": True, "all_faststart": True,
            "all_posters_same_case_timestamp": True, "all_posters_960x544": True,
            "generated_outputs_match_current_experiment": sum("frozen_experiment_identity" in a for a in assets),
            "verified_early_step_sampling_traces": len(manifest["cases"]),
            "source_data_unchanged": True,
            "video_bytes": sum(a["bytes"] for a in assets),
            "poster_bytes": sum(a["poster"]["bytes"] for a in assets),
            "largest_video": {"src": largest["src"], "bytes": largest["bytes"]},
            "codecs": {"video": ["h264"], "audio": ["aac"]},
            "errors": [],
        }
        validation["total_media_bytes"] = validation["video_bytes"] + validation["poster_bytes"]
        provenance["validation"] = validation
        public_text = json.dumps(provenance)
        for private_fragment in [str(site), str(experiment_root), str(report_dir), "/ytech", "api_key", "prompt_id"]:
            require(private_fragment not in public_text, "Private field leaked into public provenance")
        write_json(dist / "data" / "media.json", manifest)
        write_json(dist / "data" / "media-provenance.json", provenance)
        report["validation"] = validation
        report["manifest_bytes"] = sum((dist / "data" / name).stat().st_size
                                       for name in ["media.json", "media-provenance.json"])
        report["total_published_bytes"] = validation["total_media_bytes"] + report["manifest_bytes"]
        report["status"] = "passed"
        print(json.dumps({"status": "passed", "validation": validation,
                          "total_published_bytes": report["total_published_bytes"]}, indent=2))
    except Exception as error:
        report["status"] = "failed"
        report["errors"].append({"error": str(error)})
        raise
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(report_dir / "preparation-report.json", report)


if __name__ == "__main__":
    main()
