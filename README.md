# Code-Guided Video Editing

**Code-Guided Video Editing with Source-Grounded Executable Proxies**

Yuanhong Zheng · Peking University

[Project page](https://yuanhong-zheng.github.io/code-guided-video-editing/) · [Paper](https://yuanhong-zheng.github.io/code-guided-video-editing/assets/paper.pdf)

The research page organizes selected comparisons into eight OpenVE-Bench
editing categories. Each example shows the source video, executable proxy,
matched H3 output without a proxy, and output with early-step proxy guidance.
Cases are selected for a visible failure without a proxy and a clear
improvement with proxy guidance, following direct inspection of both outputs.
Each category has at most two examples; unfilled categories remain empty.
All selected examples are expanded on one page. Nearby comparisons load and play
automatically; distant video decoders are released. Playback is muted and loops,
with synchronized pause, restart, and scrubbing for each group of four.

Both output groups use the same frozen INT8 MiniMax-H3 model, seed 42,
and 20 sampling steps. The source remains active throughout. The guided group
adds the edited proxy for steps 1–5. These are selected qualitative examples,
not an aggregate benchmark evaluation.

The method section displays Figure 2 from the paper as a 3000-pixel-wide,
lossless WebP export. Both the image and its caption link to the original
vector PDF for full-resolution viewing.

## Editing and previewing

The site is buildless HTML, CSS, and JavaScript, with self-hosted fonts and media.
Update `content.json` for the reviewed descriptions, `index.template.html` for
page structure, and `dist/styles.css` / `dist/app.js` for presentation and behavior.

```sh
python3 scripts/build_page.py
python3 scripts/check_site.py
python3 scripts/serve.py
```

Open `http://localhost:8000`. The build writes all selected case cards directly into
`dist/index.html`; JavaScript is only used for playback and clipboard behavior.
Pushes to `main` deploy `dist/` through the GitHub Pages workflow.

## Media provenance

`dist/data/media.json` maps the four views for every example.
`dist/data/media-provenance.json` records the experiment identity, conditioning
schedule, file hashes, and encoded stream hashes. Published MP4s are faststart
stream-copy remuxes of the existing experiment outputs. Neither video nor audio
streams are re-encoded. Posters use the same timestamp near 30% for each case.
The optional `scripts/prepare_media.py --help` explains how to prepare the
selected media from an existing experiment checkout; it does not run a model.

Source clips and tasks come from [OpenVE-Bench](https://github.com/OpenVE-Team/OpenVE-3M).
The program-and-render workflow builds on [Code Video Model](https://github.com/code-video-model/CodeVideoModel),
and synthesis uses [MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3).
Font licenses are included alongside the self-hosted Inter and Newsreader fonts.
Media and research artifacts retain their applicable upstream terms.
