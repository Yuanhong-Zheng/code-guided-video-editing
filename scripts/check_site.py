#!/usr/bin/env python3
"""Check the expanded gallery, local assets, and frozen media provenance."""

from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def require(value, message):
    if not value:
        raise AssertionError(message)


def main():
    source = (DIST / "index.html").read_text()
    page = Page()
    page.feed(source)
    content = json.loads((ROOT / "content.json").read_text())
    media = json.loads((DIST / "data/media.json").read_text())
    provenance = json.loads((DIST / "data/media-provenance.json").read_text())
    categories = content["categories"]
    cases = [case for category in categories for case in category["cases"]]
    ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
    require(len(ids) == len(set(ids)), "Duplicate HTML IDs")
    require(len(categories) == 8 and 0 < len(cases) <= 16, "Expected eight tasks and up to sixteen reviewed cases")
    require(len({case["id"] for case in cases}) == len(cases), "Duplicate selected cases")
    require(set(media["cases"]) == {case["id"] for case in cases}, "Media case mismatch")
    for category in categories:
        require(len(category["cases"]) <= 2, "At most two reviewed cases per task")
        require(category["id"] in ids, "Task section is missing")
        for case in category["cases"]:
            require(f"case-{case['id']}" in ids, "Expanded case is missing")
    videos = [attrs for tag, attrs in page.elements if tag == "video"]
    require(len(videos) == 4 * len(cases), "Expected four video elements per case")
    expected_videos = {item["src"] for case in media["cases"].values() for item in case["media"]}
    actual_videos = {path.relative_to(DIST).as_posix() for path in (DIST / "assets/cases").rglob("*.mp4")}
    require(actual_videos == expected_videos, "Unselected or missing published video files")
    require(set(provenance["cases"]) == set(media["cases"]), "Provenance selection mismatch")
    for attrs in videos:
        require("src" not in attrs, "Video eagerly acquires a source")
        require(all(key in attrs for key in ["muted", "playsinline", "loop", "data-src"]), "Playback attributes missing")
        require(attrs.get("preload") == "none", "Video preload must be none before activation")
    require(not any(tag == "select" or attrs.get("role") == "tab" for tag, attrs in page.elements), "Gallery must have no case/category selector")
    for _, attrs in page.elements:
        for key in ["href", "src", "data-src"]:
            value = attrs.get(key)
            if not value:
                continue
            url = urlsplit(value)
            if url.scheme or url.netloc:
                require(url.scheme == "https", f"Unexpected external URL scheme: {url.scheme}")
                continue
            if url.path:
                path = (DIST / unquote(url.path)).resolve()
                require(path.is_relative_to(DIST), "Asset escapes published directory")
                require(path.is_file(), f"Missing published file: {url.path}")
            elif url.fragment:
                require(url.fragment in ids, f"Unresolved page anchor: {url.fragment}")
    # Both static language editions share the same cases, media and anchors.
    require(source.index('id="method"') < source.index('id="results"'), "Method must precede results")
    chinese_source = (DIST / "zh.html").read_text()
    chinese_page = Page()
    chinese_page.feed(chinese_source)
    require('<html lang="zh-CN">' in chinese_source, "Chinese document language missing")
    require(chinese_source.index('id="method"') < chinese_source.index('id="results"'), "Chinese method must precede results")
    chinese_ids = [attrs["id"] for _, attrs in chinese_page.elements if "id" in attrs]
    require(set(chinese_ids) == set(ids) and len(chinese_ids) == len(set(chinese_ids)), "Language anchors differ")
    chinese_videos = [attrs for tag, attrs in chinese_page.elements if tag == "video"]
    require({v["data-src"] for v in chinese_videos} == {v["data-src"] for v in videos}, "Language media differs")
    require(len(chinese_videos) == len(videos), "Chinese comparison views missing")
    benchmark = json.loads((ROOT / 'benchmark.json').read_text())
    require(benchmark == json.loads((DIST / 'data/benchmark.json').read_text()), 'Published benchmark differs from source')
    require(benchmark['model'] == 'google/gemini-3.1-pro-preview', 'Wrong benchmark evaluator')
    require(benchmark['repeats_per_video'] == 3 and benchmark['evaluated_pairs'] == 365, 'Wrong repeated evaluation scope')
    require(len(benchmark['categories']) == 8 and sum(r['n'] for r in benchmark['categories']) == 365, 'Wrong category coverage')
    require(benchmark['primary_metric'] == 'category_equal_macro_average', 'Wrong primary metric')
    require(round(benchmark['macro']['without_proxy'], 2) == 2.74 and round(benchmark['macro']['with_proxy'], 2) == 2.84, 'Wrong primary scores')
    for document in [source, chinese_source]:
        require(document.index('id="benchmark"') > max(document.index(f'id="{c["id"]}"') for c in categories), 'Benchmark must follow all showcases')
        require(document.index('id="benchmark"') < document.index('class="citation-section'), 'Benchmark must precede citation')
        require('Gemini 2.5' not in document and 'gemini-2.5' not in document, 'Only Gemini 3.1 results should be displayed')
        require('ProxyEdit-H3' in document and 'Coming soon' in document, 'Release name or Paper status missing')
        require('November 2026' not in document and '2026年11月' not in document, 'Release date must say this month')
        require('Read the paper' not in document, 'Hero paper label must be Paper')
        for r in benchmark['categories']:
            row = re.search(r'<tr[^>]*data-category="' + r['id'] + r'"[^>]*>(.*?)</tr>', document, re.S)
            require(row, 'Missing task score row')
            values = re.findall(r'<td[^>]*>(.*?)</td>', row.group(1), re.S)
            expected = [str(r['n']), f'{r["without_proxy"]:.2f}', f'{r["with_proxy"]:.2f}']
            require(values[:3] == expected, f'Incorrect published task scores: {r["id"]}')
    require(all("src" not in v and v.get("preload") == "none" for v in chinese_videos), "Chinese videos load eagerly")
    require("{{" not in source and "{{" not in chinese_source, "Unresolved template copy")
    for document, parsed, current_language in [(source, page, "en"), (chinese_source, chinese_page, "zh-CN")]:
        links = [a for tag, a in parsed.elements if tag == "a" and "data-language-page" in a]
        require({a["href"] for a in links} == {"index.html", "zh.html"}, "Language switch missing")
        require([a["hreflang"] for a in links if a.get("aria-current") == "page"] == [current_language], "Wrong active language")
        for _, attrs in parsed.elements:
            for key in ["href", "src", "data-src"]:
                url = urlsplit(attrs.get(key, ""))
                if url.scheme or url.netloc or not url.path:
                    continue
                path = (DIST / unquote(url.path)).resolve()
                require(path.is_relative_to(DIST) and path.is_file(), "Missing language edition asset")

    for cid, case in provenance["cases"].items():
        guided = case["conditioning_validation"]["with-proxy"]
        require(guided["proxy_condition_steps"] == list(range(1, 6)), f"Wrong proxy schedule: {cid}")
        require(guided["source_condition_steps"] == list(range(1, 21)), f"Wrong source schedule: {cid}")
        require(guided["actual_sampling_trace_verified"] or (
            guided.get("conditioning_metadata_verified") and
            guided.get("schedule_evidence") == "native_conditioning_record"
        ), f"Unverified early-step evidence: {cid}")
        if guided.get("conditioning_metadata_verified"):
            require(guided.get("same_source_reference_verified"), f"Unmatched source reference: {cid}")
            require(guided["source_reference_sha256"] ==
                    case["conditioning_validation"]["without-proxy"]["source_reference_sha256"],
                    f"Source reference hashes differ: {cid}")
        dimensions = set()
        for item in case["media"]:
            video = DIST / item["src"]
            require(sha256(video.read_bytes()).hexdigest() == item["published_file_sha256"], f"Video changed: {item['src']}")
            require(item["source_video_packet_sha256"] == item["published_video_packet_sha256"], "Encoded video content changed")
            require(item["all_encoded_streams_preserved"] and item["faststart"], "Invalid remux")
            dimensions.add((item["width"], item["height"], item["fps"], item["frames"]))
            require(item["width"] > 0 and item["height"] > 0 and item["fps"] > 0, "Invalid native media format")
            poster = item["poster"]
            require(sha256((DIST / poster["src"]).read_bytes()).hexdigest() == poster["sha256"], "Poster changed")
        require(len(dimensions) == 1, f"Four views have different formats or timelines: {cid}")
        width, height, fps, frames = next(iter(dimensions))
        require(media["cases"][cid].get("fps", 24) == fps, f"Playback FPS differs from source: {cid}")
        require(abs(media["cases"][cid]["duration"] - frames / fps) < 1e-8, f"Playback timeline differs from source: {cid}")
    # Runtime artifacts and private infrastructure must never enter the site.
    private_patterns = [r"/ytech[^\s\"']+", r"\b(?:olp_|gho_)[A-Za-z0-9]{12,}", r"\b(?:sk-|AIza)[A-Za-z0-9_-]{16,}", r"https?://(?:10\.|127\.|localhost)"]
    for path in DIST.rglob("*"):
        if path.suffix in {".html", ".js", ".css", ".json", ".svg"}:
            text = path.read_text()
            require(not any(re.search(pattern, text) for pattern in private_patterns), f"Private data in {path.relative_to(DIST)}")
    size = sum(path.stat().st_size for path in DIST.rglob("*") if path.is_file())
    print(json.dumps({"languages": ["en", "zh-CN"], "categories": 8, "cases": len(cases), "videos": len(videos), "empty_categories": [c["id"] for c in categories if not c["cases"]], "verified_media": True, "benchmark_pairs": benchmark['evaluated_pairs'], "benchmark_repeats": 3, "trained_model_release": "ProxyEdit-H3 / this month", "published_bytes": size, "all_cases_expanded": True}, indent=2))


if __name__ == "__main__":
    main()
