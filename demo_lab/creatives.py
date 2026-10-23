"""Creative fixtures: VAST XML / declared JSON -> format_spec (pure, stdlib only).

The format_spec uses the CONTRACTS canonical key spellings: duration_sec,
width/height, mime_type, bitrate_kbps. VAST version is sent as
``vast_version`` (CONTRACTS names no key for it; see lab_report.md).
These are declared ad metadata: no media file is downloaded or inspected.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from .scenarios import DATA_DIR, load_json

CREATIVE_DIR = DATA_DIR / "creatives"


def _duration_to_sec(text: str) -> float:
    hh, mm, ss = text.strip().split(":")
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def parse_vast(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    spec: dict[str, Any] = {"vast_version": root.attrib.get("version")}
    dur = root.find(".//Linear/Duration")
    if dur is not None and (dur.text or "").strip():
        sec = _duration_to_sec(dur.text)
        spec["duration_sec"] = int(sec) if sec == int(sec) else sec
    mf = root.find(".//MediaFiles/MediaFile")
    if mf is not None:
        if mf.attrib.get("type"):
            spec["mime_type"] = mf.attrib["type"]
        for key, out in (("width", "width"), ("height", "height"), ("bitrate", "bitrate_kbps")):
            if mf.attrib.get(key):
                spec[out] = int(mf.attrib[key])
    return spec


def format_spec_for(fixture: dict[str, Any]) -> dict[str, Any]:
    src = CREATIVE_DIR / fixture["source"]
    text = src.read_text(encoding="utf-8")
    spec = parse_vast(text) if src.suffix == ".xml" else json.loads(text)
    spec["channel"] = fixture["channel"]
    spec["slot"] = fixture["slot"]
    return spec


def load_manifest() -> dict[str, Any]:
    m = load_json("creatives/manifest.json")
    m.pop("_note", None)
    return m
