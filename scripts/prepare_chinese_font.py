#!/usr/bin/env python3
"""Subset a local Noto Sans SC variable font to the Chinese edition's copy."""
import argparse
from hashlib import sha256
from pathlib import Path
import re
import shutil

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, required=True)
    parser.add_argument('--license', type=Path, required=True)
    args = parser.parse_args()
    text = (ROOT / 'content.zh.json').read_text() + (ROOT / 'locales/zh.json').read_text()
    font = TTFont(args.font)
    options = subset.Options()
    options.name_IDs = ['*']
    options.name_legacy = True
    options.name_languages = ['*']
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    font.flavor = 'woff2'
    output = ROOT / 'dist/assets/fonts/noto-sans-sc-project.woff2'
    font.save(output)
    exported = TTFont(output)
    required = {ord(c) for c in text if '\u4e00' <= c <= '\u9fff'}
    assert required.issubset(exported.getBestCmap()), 'Chinese glyphs missing'
    shutil.copyfile(args.license, output.with_name('NotoSansSC-OFL.txt'))
    stylesheet = ROOT / 'dist/styles.css'
    version = sha256(output.read_bytes()).hexdigest()[:12]
    css = re.sub(r'assets/fonts/noto-sans-sc-project\.woff2(?:\?v=[0-9a-f]+)?',
                 f'assets/fonts/noto-sans-sc-project.woff2?v={version}', stylesheet.read_text())
    stylesheet.write_text(css)
    print(f'Prepared {output.name}: {output.stat().st_size} bytes; {len(required)} Chinese characters covered.')


if __name__ == '__main__':
    main()
