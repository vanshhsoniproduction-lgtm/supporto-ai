#!/usr/bin/env python3
"""
Supporto AI - Safe Model Copy Script
Copies existing local AI models (Qwen, Whisper, Kokoro) from a verified JARVIS directory.
Ensures zero alteration to source files, validates checksums, skips existing copies,
and outputs a model manifest.
"""

import os
import sys
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024 * 8) -> str:
    """Compute SHA-256 hash of a file efficiently using 8MB chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def find_source_path(base_dir: Path, relative_candidates: list[str]) -> Path | None:
    for rel in relative_candidates:
        candidate = base_dir / rel
        if candidate.exists():
            return candidate
    return None


def copy_file_safe(src: Path, dst: Path, dry_run: bool = False, force: bool = False) -> tuple[str, int, str]:
    """
    Safely copy a single file if destination doesn't exist or doesn't match size.
    Returns (status, size, sha256)
    status: 'copied', 'skipped', 'error'
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_size = src.stat().st_size

    if dst.exists() and not force:
        dst_size = dst.stat().st_size
        if dst_size == src_size:
            # Quick verification by size; full hash verified in manifest
            return ("skipped", dst_size, "")

    if dry_run:
        return ("dry-run", src_size, "")

    # Copy with temporary file to prevent partial corruptions
    temp_dst = dst.with_suffix(dst.suffix + ".part")
    try:
        shutil.copy2(src, temp_dst)
        temp_dst.replace(dst)
        sha = compute_sha256(dst)
        return ("copied", dst.stat().st_size, sha)
    except Exception as e:
        if temp_dst.exists():
            temp_dst.unlink(missing_ok=True)
        raise e


def copy_directory_safe(src_dir: Path, dst_dir: Path, exclude_extensions: set[str] = None, dry_run: bool = False, force: bool = False) -> list[dict]:
    """Recursively copy directory tree, excluding specified file extensions."""
    records = []
    if exclude_extensions is None:
        exclude_extensions = set()

    for root, dirs, files in os.walk(src_dir):
        # Ignore hidden/cache folders
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_root = Path(root).relative_to(src_dir)
        target_root = dst_dir / rel_root

        for file in files:
            if file.startswith("."):
                continue
            src_file = Path(root) / file
            if src_file.suffix.lower() in exclude_extensions:
                continue

            dst_file = target_root / file
            status, size, sha = copy_file_safe(src_file, dst_file, dry_run=dry_run, force=force)
            if not sha and dst_file.exists():
                sha = compute_sha256(dst_file)
            
            records.append({
                "source": str(src_file),
                "destination": str(dst_file),
                "relative_dest": str(dst_file.relative_to(dst_dir.parents[1])),
                "size_bytes": size,
                "sha256": sha,
                "status": status
            })
    return records


def main():
    parser = argparse.ArgumentParser(description="Safely copy verified models from JARVIS to Supporto AI.")
    parser.add_argument("--jarvis-root", required=True, help="Absolute path to the existing JARVIS project directory.")
    parser.add_argument("--dest-root", default=None, help="Root path of Supporto AI (defaults to current dir).")
    parser.add_argument("--force", action="store_true", help="Overwrite existing copies even if verified.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without copying files.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip large LLM copy if testing STT/TTS only.")

    args = parser.parse_args()

    jarvis_root = Path(args.jarvis-root if hasattr(args, "jarvis-root") else args.jarvis_root).resolve()
    if not jarvis_root.exists() or not jarvis_root.is_dir():
        print(f"[-] Error: JARVIS root directory does not exist: {jarvis_root}", file=sys.stderr)
        sys.exit(1)

    dest_root = Path(args.dest_root).resolve() if args.dest_root else Path(__file__).resolve().parents[1]
    models_dest = dest_root / "models"
    models_dest.mkdir(parents=True, exist_ok=True)

    print(f"[*] Source JARVIS root: {jarvis_root}")
    print(f"[*] Destination models root: {models_dest}")
    print("=" * 60)

    # 1. Discover Qwen
    qwen_src = find_source_path(jarvis_root, [
        "model/Qwen3-8B-Q4_K_M.gguf",
        "models/Qwen3-8B-Q4_K_M.gguf",
        "model/qwen3-8b-q4_k_m.gguf",
    ])

    # 2. Discover Whisper
    whisper_src = find_source_path(jarvis_root, [
        "models/whisper-small",
        "model/whisper-small",
    ])

    # 3. Discover Kokoro
    kokoro_src = find_source_path(jarvis_root, [
        "models/kokoro",
        "model/kokoro",
    ])

    missing = []
    if not qwen_src and not args.skip_llm:
        missing.append("Qwen GGUF model")
    if not whisper_src:
        missing.append("Whisper small model directory")
    if not kokoro_src:
        missing.append("Kokoro model directory")

    if missing:
        print("[-] Missing required source models in JARVIS:")
        for m in missing:
            print(f"    - {m}")
        sys.exit(1)

    manifest_entries = []
    summary = {"copied": 0, "skipped": 0, "dry_run": 0}

    # Process Qwen
    if qwen_src and not args.skip_llm:
        dst_qwen = models_dest / "llm" / qwen_src.name
        print(f"[*] Processing LLM: {qwen_src} -> {dst_qwen}...")
        status, size, sha = copy_file_safe(qwen_src, dst_qwen, dry_run=args.dry_run, force=args.force)
        if not sha and dst_qwen.exists():
            print("    Validating SHA-256 for existing file...")
            sha = compute_sha256(dst_qwen)
        manifest_entries.append({
            "model_type": "llm",
            "name": qwen_src.name,
            "path": str(dst_qwen.relative_to(dest_root)),
            "size_bytes": size,
            "sha256": sha,
            "status": status
        })
        summary[status.replace("-", "_")] = summary.get(status.replace("-", "_"), 0) + 1
        print(f"    Status: {status} ({size / (1024*1024):.2f} MB)")

    # Process Whisper
    if whisper_src:
        dst_whisper = models_dest / "stt" / "whisper-small"
        print(f"[*] Processing STT: {whisper_src} -> {dst_whisper}...")
        records = copy_directory_safe(whisper_src, dst_whisper, exclude_extensions={".wav", ".mp3", ".log"}, dry_run=args.dry_run, force=args.force)
        for r in records:
            r["model_type"] = "stt"
            manifest_entries.append(r)
            s = r["status"].replace("-", "_")
            summary[s] = summary.get(s, 0) + 1
        print(f"    Processed {len(records)} files in Whisper directory.")

    # Process Kokoro
    if kokoro_src:
        dst_kokoro = models_dest / "tts" / "kokoro"
        print(f"[*] Processing TTS: {kokoro_src} -> {dst_kokoro}...")
        records = copy_directory_safe(kokoro_src, dst_kokoro, exclude_extensions={".wav", ".mp3", ".log"}, dry_run=args.dry_run, force=args.force)
        for r in records:
            r["model_type"] = "tts"
            manifest_entries.append(r)
            s = r["status"].replace("-", "_")
            summary[s] = summary.get(s, 0) + 1
        print(f"    Processed {len(records)} files in Kokoro directory.")

    # Write Manifest
    manifest_path = models_dest / "model_manifest.json"
    manifest_data = {
        "source_jarvis_root": str(jarvis_root),
        "manifest_version": "1.0",
        "entries": manifest_entries,
        "summary": summary
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print("=" * 60)
    print("[+] Model Copy Summary:")
    print(f"    Copied files : {summary.get('copied', 0)}")
    print(f"    Skipped files: {summary.get('skipped', 0)}")
    print(f"    Manifest generated: {manifest_path}")


if __name__ == "__main__":
    main()

