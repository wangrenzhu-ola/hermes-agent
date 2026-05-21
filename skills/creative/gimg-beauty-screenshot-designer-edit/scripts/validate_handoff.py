#!/usr/bin/env python3
"""Validate a GIMG beauty screenshot designer handoff manifest.

This intentionally uses only Python stdlib so it can run in a clean public repo.
It performs structural checks, path checks, and safety/readback checks. It does
not validate private generation prompts or real App Store assets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_TOP = ["package_id", "app", "locale", "target_size", "screenshots", "safety", "return_contract"]
REQUIRED_SCREENSHOT = [
    "id", "sequence", "image_path", "title_copy", "background", "person",
    "device_frame", "decorations", "editable_layers", "locked_layers",
    "review_safety", "generation_evidence", "designer_notes", "return_expected",
]
SAFE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def require_keys(obj: dict, keys: list[str], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        fail(f"{where} missing required keys: {', '.join(missing)}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: validate_handoff.py <manifest.json>", file=sys.stderr)
        return 2

    manifest_path = Path(argv[1]).expanduser().resolve()
    if not manifest_path.exists():
        fail(f"manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require_keys(manifest, REQUIRED_TOP, "manifest")

    screenshots = manifest["screenshots"]
    if not isinstance(screenshots, list) or not (3 <= len(screenshots) <= 5):
        fail("manifest.screenshots must contain 3-5 records")

    seen_ids: set[str] = set()
    seen_sequences: set[int] = set()
    root = manifest_path.parent
    for idx, shot in enumerate(screenshots, start=1):
        require_keys(shot, REQUIRED_SCREENSHOT, f"screenshots[{idx}]")
        shot_id = str(shot["id"])
        if shot_id in seen_ids:
            fail(f"duplicate screenshot id: {shot_id}")
        seen_ids.add(shot_id)
        seq = int(shot["sequence"])
        if seq in seen_sequences:
            fail(f"duplicate sequence: {seq}")
        seen_sequences.add(seq)

        image_path = root / shot["image_path"]
        if image_path.suffix.lower() not in SAFE_IMAGE_SUFFIXES:
            fail(f"unsupported image suffix for {shot_id}: {image_path.suffix}")
        if not image_path.exists():
            fail(f"image path missing for {shot_id}: {image_path}")

        if not shot["editable_layers"] or not shot["locked_layers"]:
            fail(f"{shot_id} must have both editable_layers and locked_layers")
        if not shot["review_safety"]:
            fail(f"{shot_id} must have review_safety notes")
        evidence = shot["generation_evidence"]
        if not isinstance(evidence, dict) or "redaction_status" not in evidence:
            fail(f"{shot_id} generation_evidence.redaction_status is required")
        if evidence.get("redaction_status") not in {"synthetic_public_sample", "redacted", "private_internal_only"}:
            fail(f"{shot_id} has invalid redaction_status: {evidence.get('redaction_status')}")

    rc = manifest["return_contract"]
    if "designer_change_log_required" not in rc or not rc["designer_change_log_required"]:
        fail("return_contract.designer_change_log_required must be true")
    if "returned_image_pattern" not in rc:
        fail("return_contract.returned_image_pattern is required")

    print(json.dumps({
        "status": "PASS",
        "manifest": str(manifest_path),
        "screenshots": len(screenshots),
        "ids": sorted(seen_ids),
        "sequences": sorted(seen_sequences),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
