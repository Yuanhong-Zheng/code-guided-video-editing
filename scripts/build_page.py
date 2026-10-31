#!/usr/bin/env python3
"""Build the complete, buildless research page from reviewed content and media."""

from html import escape
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ROLES = {
    "source": ("Source video", "INPUT", "source"),
    "proxy": ("Executable proxy", "PLAN", "proxy"),
    "without-proxy": ("Without proxy", "H3", "baseline"),
    "with-proxy": ("With proxy", "EARLY-STEP", "guided"),
}
PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 2 10 6-10 6Z"/></svg>'
RESTART = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4a6 6 0 1 1-1 6" fill="none"/><path d="M3 1v4h4" fill="none"/></svg>'


def panel(item: dict, title: str) -> str:
    label, hint, class_name = ROLES[item["role"]]
    src, poster = escape(item["src"], quote=True), escape(item["poster"], quote=True)
    aria = escape(f"{label}: {title}", quote=True)
    return f'''<figure class="video-panel {class_name}" data-role="{item['role']}">
      <figcaption class="view-label"><span>{label}</span><span>{hint}</span></figcaption>
      <div class="video-frame">
        <img class="video-poster" src="{poster}" alt="{aria}" width="960" height="544" loading="lazy" decoding="async">
        <video muted playsinline loop preload="none" data-src="{src}" aria-label="{aria}" tabindex="-1"></video>
        <a class="open-video" href="{src}" target="_blank" rel="noopener" aria-label="Open {aria} in a new tab" title="Open this video">↗</a>
      </div>
    </figure>'''


def card(case: dict, media: dict) -> str:
    cid, title = escape(case["id"]), escape(case["title"])
    duration = media["duration"]
    views = "\n".join(panel(item, case["title"]) for item in media["media"])
    return f'''<article class="case-card" id="case-{cid}" data-case-id="{cid}" data-duration="{duration:.8f}" aria-labelledby="title-{cid}">
    <div class="case-heading"><h3 id="title-{cid}">{title}</h3><a class="case-id" href="#case-{cid}" aria-label="Link to case {cid}">CASE {cid} ↗</a></div>
    <p class="edit-request"><b>Edit request</b>{escape(case['edit'])}</p>
    <div class="video-grid">{views}</div>
    <div class="case-controls" role="group" aria-label="Synchronized playback for case {cid}">
      <button class="transport" data-action="play" type="button" aria-label="Play all four videos" aria-pressed="false">{PLAY}<span>Play</span></button>
      <button class="transport" data-action="restart" type="button" aria-label="Restart all four videos">{RESTART}<span>Restart</span></button>
      <input class="seek" type="range" min="0" max="{duration:.8f}" value="0" step="0.04166667" aria-label="Seek all four videos in case {cid}">
      <span class="time-label">0.0 / {duration:.1f} s</span><span class="loop-note">4 views · muted · loop</span><span class="case-status" role="status">Loading…</span>
    </div>
    <p class="case-observation">{escape(case['observation'])}</p>
    <div class="case-error" role="status"><span>Video playback could not load. You can retry or open an individual video.</span><button type="button" data-action="retry">Retry</button></div>
  </article>'''


def main() -> None:
    content = json.loads((ROOT / "content.json").read_text())
    media = json.loads((DIST / "data/media.json").read_text())
    sections = []
    for i, category in enumerate(content["categories"], 1):
        cards = "\n".join(card(case, media["cases"][case["id"]]) for case in category["cases"])
        if not cards:
            cards = f'<div class="empty-showcase">{escape(category.get("empty_message", "Showcases to be added."))}</div>'
        sections.append(f'''<section class="task-section container" id="{category['id']}" aria-labelledby="task-{category['id']}">
          <div class="task-heading"><span class="task-number" aria-hidden="true">{i:02}</span><div><h2 id="task-{category['id']}">{escape(category['title'])}</h2><p>{escape(category['description'])}</p></div></div>
          {cards}
        </section>''')
    template = (ROOT / "index.template.html").read_text()
    assert template.count("{{SHOWCASES}}") == 1
    html = template.replace("{{SHOWCASES}}", "\n".join(sections))
    html = html.replace("{{CASE_COUNT}}", str(sum(len(c["cases"]) for c in content["categories"])))
    html = html.replace("{{CATEGORY_COUNT}}", str(len(content["categories"])))
    for name, attribute in [
        ("assets/paper.pdf", "href"),
        ("assets/method-overview.pdf", "href"),
        ("assets/method-overview.webp", "src"),
        ("styles.css", "href"),
        ("app.js", "src"),
    ]:
        version = sha256((DIST / name).read_bytes()).hexdigest()[:12]
        html = html.replace(f'{attribute}="{name}"', f'{attribute}="{name}?v={version}"')
    (DIST / "index.html").write_text(html)
    print(f"Built {len(sections)} task sections, {sum(len(c['cases']) for c in content['categories'])} complete comparisons.")


if __name__ == "__main__":
    main()
