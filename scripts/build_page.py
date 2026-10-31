#!/usr/bin/env python3
"""Build both language editions from one template and shared experiment media."""

from html import escape
from hashlib import sha256
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
ROLES = {
    'source': ('SOURCE', 'INPUT_HINT', 'source'),
    'proxy': ('PROXY', 'PLAN_HINT', 'proxy'),
    'without-proxy': ('WITHOUT_PROXY', None, 'baseline'),
    'with-proxy': ('WITH_PROXY', 'GUIDED_HINT', 'guided'),
}
PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 2 10 6-10 6Z"/></svg>'
RESTART = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4a6 6 0 1 1-1 6" fill="none"/><path d="M3 1v4h4" fill="none"/></svg>'


def text(ui, key, **values):
    return escape(ui[key].format(**values), quote=True)


def panel(item, title, ui):
    label_key, hint_key, class_name = ROLES[item['role']]
    label = ui[label_key]
    hint = ui[hint_key] if hint_key else 'H3'
    src, poster = escape(item['src'], quote=True), escape(item['poster'], quote=True)
    aria = f'{label}: {title}'
    return f'''<figure class="video-panel {class_name}" data-role="{item['role']}">
      <figcaption class="view-label"><span>{escape(label)}</span><span>{escape(hint)}</span></figcaption>
      <div class="video-frame">
        <img class="video-poster" src="{poster}" alt="{escape(aria, quote=True)}" width="960" height="544" loading="lazy" decoding="async">
        <video muted playsinline loop preload="none" data-src="{src}" aria-label="{escape(aria, quote=True)}" tabindex="-1"></video>
        <a class="open-video" href="{src}" target="_blank" rel="noopener" aria-label="{text(ui, 'OPEN_VIDEO_LABEL', label=aria)}" title="{text(ui, 'OPEN_VIDEO')}">↗</a>
      </div>
    </figure>'''


def card(case, media, ui):
    cid, title = escape(case['id']), escape(case['title'])
    duration = media['duration']
    views = '\n'.join(panel(item, case['title'], ui) for item in media['media'])
    return f'''<article class="case-card" id="case-{cid}" data-case-id="{cid}" data-duration="{duration:.8f}" aria-labelledby="title-{cid}">
    <div class="case-heading"><h3 id="title-{cid}">{title}</h3><a class="case-id" href="#case-{cid}" aria-label="{text(ui, 'CASE_LINK', id=cid)}">{text(ui, 'CASE_LABEL')} {cid} ↗</a></div>
    <p class="edit-request"><b>{text(ui, 'EDIT_REQUEST')}</b>{escape(case['edit'])}</p>
    <div class="video-grid">{views}</div>
    <div class="case-controls" role="group" aria-label="{text(ui, 'CONTROLS_LABEL', id=cid)}">
      <button class="transport" data-action="play" type="button" aria-label="{text(ui, 'PLAY_ALL')}" aria-pressed="false">{PLAY}<span>{text(ui, 'PLAY')}</span></button>
      <button class="transport" data-action="restart" type="button" aria-label="{text(ui, 'RESTART_ALL')}">{RESTART}<span>{text(ui, 'RESTART')}</span></button>
      <input class="seek" type="range" min="0" max="{duration:.8f}" value="0" step="0.04166667" aria-label="{text(ui, 'SEEK_ALL', id=cid)}">
      <span class="time-label">0.0 / {duration:.1f} {text(ui, 'TIME_UNIT')}</span><span class="loop-note">{text(ui, 'LOOP_NOTE')}</span><span class="case-status" role="status">{text(ui, 'LOADING')}</span>
    </div>
    <p class="case-observation">{escape(case['observation'])}</p>
    <div class="case-error" role="status"><span>{text(ui, 'VIDEO_ERROR')}</span><button type="button" data-action="retry">{text(ui, 'RETRY')}</button></div>
  </article>'''


def language_switch(lang, ui):
    links = []
    for code, page, label, aria in [
        ('en', 'index.html', 'EN', 'Switch to English'),
        ('zh-CN', 'zh.html', '中文', '切换为中文'),
    ]:
        active = ' aria-current="page"' if code == lang else ''
        links.append(f'<a href="{page}" data-language-page="{page}" hreflang="{code}" lang="{code}" aria-label="{aria}"{active}>{label}</a>')
    return f'<div class="language-switch" role="group" aria-label="{text(ui, "LANGUAGE_LABEL")}">{"".join(links)}</div>'


def edition(content, media, ui, lang, output):
    sections = []
    for i, category in enumerate(content['categories'], 1):
        cards = '\n'.join(card(case, media['cases'][case['id']], ui) for case in category['cases'])
        if not cards:
            cards = f'<div class="empty-showcase">{escape(category.get("empty_message", ui["EMPTY_MESSAGE"]))}</div>'
        sections.append(f'''<section class="task-section container" id="{category['id']}" aria-labelledby="task-{category['id']}">
          <div class="task-heading"><span class="task-number" aria-hidden="true">{i:02}</span><div><h2 id="task-{category['id']}">{escape(category['title'])}</h2><p>{escape(category['description'])}</p></div></div>
          {cards}
        </section>''')
    case_count = sum(len(c['cases']) for c in content['categories'])
    values = {key: value for key, value in ui.items()}
    values['META_DESCRIPTION'] = ui['META_DESCRIPTION'].format(case_count=case_count)
    values.update({
        'LANG': lang,
        'TITLE': content['title'],
        'AUTHOR': content['author'],
        'AFFILIATION': content['affiliation'],
        'CANONICAL': content['canonical'] + (output if lang != 'en' else ''),
        'EN_CANONICAL': content['canonical'],
        'ZH_CANONICAL': content['canonical'] + 'zh.html',
        'CATEGORY_COUNT': str(len(content['categories'])),
        'CASE_COUNT': str(case_count),
        'SHOWCASES': '\n'.join(sections),
        'LANGUAGE_SWITCH': language_switch(lang, ui),
        'RUNTIME_COPY': json.dumps({
            'play': ui['PLAY'], 'pause': ui['PAUSE'],
            'playAll': ui['PLAY_ALL'], 'pauseAll': ui['PAUSE_ALL'],
            'timeUnit': ui['TIME_UNIT'],
            'clipboardSuccess': ui['CLIPBOARD_SUCCESS'],
            'clipboardError': ui['CLIPBOARD_ERROR'],
        }, ensure_ascii=False).replace('<', '\\u003c'),
    })
    raw = {'SHOWCASES', 'LANGUAGE_SWITCH', 'RUNTIME_COPY'}
    def replace(match):
        key = match.group(1)
        value = values[key]
        return value if key in raw or key.endswith('_HTML') else escape(value, quote=True)
    html = re.sub(r'\{\{([A-Z_]+)\}\}', replace, (ROOT / 'index.template.html').read_text())
    if '{{' in html:
        raise ValueError('Unresolved template token')
    for name, attribute in [
        ('assets/paper.pdf', 'href'), ('assets/method-overview.pdf', 'href'),
        ('assets/method-overview.webp', 'src'), ('styles.css', 'href'), ('app.js', 'src'),
    ]:
        version = sha256((DIST / name).read_bytes()).hexdigest()[:12]
        html = html.replace(f'{attribute}="{name}"', f'{attribute}="{name}?v={version}"')
    (DIST / output).write_text(html)
    print(f'Built {output}: {len(sections)} tasks, {case_count} complete comparisons ({lang}).')


def main():
    media = json.loads((DIST / 'data/media.json').read_text())
    contents = [json.loads((ROOT / name).read_text()) for name in ['content.json', 'content.zh.json']]
    selection = lambda c: [(g['id'], [x['id'] for x in g['cases']]) for g in c['categories']]
    assert selection(contents[0]) == selection(contents[1]), 'Language editions must show the same selected cases'
    for content, code, lang, output in zip(contents, ['en', 'zh'], ['en', 'zh-CN'], ['index.html', 'zh.html']):
        ui = json.loads((ROOT / 'locales' / f'{code}.json').read_text())
        edition(content, media, ui, lang, output)


if __name__ == '__main__':
    main()
