/* Four aligned views per case; only nearby cases acquire media sources. */
"use strict";

const messages = JSON.parse(document.getElementById("ui-copy").textContent);
function syncLanguageLinks() {
  document.querySelectorAll("[data-language-page]").forEach(link => {
    link.href = link.dataset.languagePage + location.hash;
  });
}
syncLanguageLinks();
addEventListener("hashchange", syncLanguageLinks);

const PLAY_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 2 10 6-10 6Z"/></svg>';
const PAUSE_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2h3v12H4zM10 2h3v12h-3z"/></svg>';
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

class Comparison {
  constructor(card) {
    this.card = card;
    this.grid = card.querySelector(".video-grid");
    this.videos = [...card.querySelectorAll("video")];
    this.playButton = card.querySelector('[data-action="play"]');
    this.seek = card.querySelector(".seek");
    this.timeLabel = card.querySelector(".time-label");
    this.duration = Number(card.dataset.duration);
    this.position = 0;
    this.loaded = false;
    this.ready = false;
    this.visible = false;
    this.playing = false;
    this.userPaused = false;
    this.failed = false;
    this.playEpoch = 0;
    this.animation = 0;
    this.lastCorrection = 0;

    for (const video of this.videos) {
      video.muted = true;
      video.defaultMuted = true;
      video.addEventListener("loadeddata", () => this.onReady());
      video.addEventListener("canplay", () => this.onReady());
      video.addEventListener("error", () => {
        if (!this.loaded) return;
        this.failed = true;
        this.pause();
        this.card.classList.add("has-error");
        this.card.classList.remove("is-loading");
        this.card.dataset.state = "error";
      });
      video.addEventListener("click", () => this.toggle());
    }
    this.playButton.addEventListener("click", () => this.toggle());
    card.querySelector('[data-action="restart"]').addEventListener("click", () => {
      this.setPosition(0);
      this.load();
      this.tryPlay();
    });
    this.seek.addEventListener("input", () => this.setPosition(Number(this.seek.value)));
    card.querySelector('[data-action="retry"]').addEventListener("click", () => {
      this.unload();
      this.failed = false;
      this.userPaused = false;
      this.card.classList.remove("has-error");
      this.load();
    });
    this.card.dataset.state = "idle";
    this.renderControls();
  }

  load() {
    if (this.loaded || this.failed) return;
    this.loaded = true;
    this.ready = false;
    this.card.dataset.loaded = "true";
    this.card.dataset.state = "loading";
    this.card.classList.add("is-loading");
    for (const video of this.videos) {
      video.preload = "auto";
      video.src = video.dataset.src;
      video.load();
    }
  }

  onReady() {
    if (!this.loaded || this.failed) return;
    for (const video of this.videos) {
      video.closest(".video-panel").classList.toggle("is-ready", video.readyState >= 2);
    }
    if (this.ready || this.videos.some(v => v.readyState < 2)) return;
    this.ready = true;
    this.card.classList.remove("is-loading");
    this.card.dataset.state = "paused";
    this.setPosition(this.position);
    this.tryPlay();
  }

  unload() {
    if (!this.loaded) return;
    this.pause();
    this.loaded = false;
    this.ready = false;
    this.card.dataset.loaded = "false";
    this.card.dataset.state = this.failed ? "error" : "idle";
    this.card.classList.remove("is-loading");
    for (const video of this.videos) {
      video.removeAttribute("src");
      video.preload = "none";
      video.load();
      video.closest(".video-panel").classList.remove("is-ready");
    }
  }

  setVisible(visible) {
    this.visible = visible;
    if (!visible || document.hidden) this.pause();
    else this.tryPlay();
    this.renderControls();
  }

  toggle() {
    this.userPaused = !this.userPaused;
    if (this.userPaused) this.pause();
    else {
      this.load();
      this.tryPlay();
    }
    this.renderControls();
  }

  async tryPlay() {
    if (!this.loaded || !this.ready || !this.visible || this.userPaused || this.failed || document.hidden || this.playing) return;
    const epoch = ++this.playEpoch;
    this.playing = true;
    this.card.dataset.state = "playing";
    this.renderControls();
    try {
      await Promise.all(this.videos.map(video => video.play()));
      if (epoch !== this.playEpoch) {
        if (!this.playing) this.videos.forEach(video => video.pause());
        return;
      }
      this.tick();
    } catch (error) {
      if (epoch !== this.playEpoch || error.name === "AbortError") return;
      this.pause();
      // Muted autoplay is normally allowed. Retain a usable Play control when
      // a browser's user policy requires an explicit gesture.
      this.userPaused = true;
      this.renderControls();
    }
  }

  pause() {
    ++this.playEpoch;
    if (this.loaded && this.ready) this.position = this.videos[0].currentTime;
    this.playing = false;
    for (const video of this.videos) video.pause();
    cancelAnimationFrame(this.animation);
    if (this.loaded && this.ready && !this.failed) this.card.dataset.state = "paused";
    this.renderControls();
    this.renderTime();
  }

  setPosition(value) {
    this.position = clamp(value, 0, Math.max(0, this.duration - 1 / 24));
    if (this.loaded && this.ready) {
      for (const video of this.videos) {
        if (video.readyState >= 1) video.currentTime = this.position;
      }
    }
    this.renderTime();
  }

  tick(now = 0) {
    if (!this.playing || !this.loaded) return;
    this.position = this.videos[0].currentTime;
    if (now - this.lastCorrection > 200) {
      for (const video of this.videos.slice(1)) {
        if (!video.seeking && video.readyState >= 2 && Math.abs(video.currentTime - this.position) > 0.14) {
          video.currentTime = this.position;
        }
      }
      this.lastCorrection = now;
    }
    this.renderTime();
    this.animation = requestAnimationFrame(time => this.tick(time));
  }

  renderControls() {
    const active = !this.userPaused && this.visible && !this.failed;
    this.playButton.innerHTML = `${active ? PAUSE_ICON : PLAY_ICON}<span>${active ? messages.pause : messages.play}</span>`;
    this.playButton.setAttribute("aria-label", active ? messages.pauseAll : messages.playAll);
    this.playButton.setAttribute("aria-pressed", String(active));
  }

  renderTime() {
    const position = clamp(this.position, 0, this.duration);
    this.seek.value = position;
    this.seek.style.setProperty("--progress", `${100 * position / this.duration}%`);
    this.timeLabel.textContent = `${position.toFixed(1)} / ${this.duration.toFixed(1)} ${messages.timeUnit}`;
  }
}

const comparisons = [...document.querySelectorAll(".case-card")].map(card => new Comparison(card));
let viewportUpdate = 0;

function updateViewport() {
  viewportUpdate = 0;
  const headerBottom = document.querySelector(".site-header").getBoundingClientRect().bottom;
  const center = (innerHeight + headerBottom) / 2;
  const geometry = comparisons.map(comparison => {
    const rect = comparison.grid.getBoundingClientRect();
    const shown = Math.max(0, Math.min(rect.bottom, innerHeight) - Math.max(rect.top, headerBottom));
    return {
      comparison,
      visible: shown >= Math.min(60, rect.height * 0.22),
      nearby: rect.bottom > headerBottom - 180 && rect.top < innerHeight + 180,
      distance: Math.abs((rect.top + rect.bottom) / 2 - center),
    };
  });
  const visible = geometry.filter(item => item.visible);
  const selected = new Set(visible.map(item => item.comparison));
  const limit = Math.max(3, selected.size);
  for (const item of geometry.filter(item => item.nearby).sort((a, b) => a.distance - b.distance)) {
    if (selected.size >= limit) break;
    selected.add(item.comparison);
  }
  // Release distant decoders before loading the next group, keeping the long
  // page inexpensive without hiding any task or case.
  for (const { comparison, visible: isVisible } of geometry) {
    comparison.setVisible(isVisible);
    if (!selected.has(comparison)) comparison.unload();
  }
  for (const comparison of selected) {
    comparison.load();
    comparison.tryPlay();
  }
}

function scheduleViewportUpdate() {
  if (!viewportUpdate) viewportUpdate = requestAnimationFrame(updateViewport);
}

addEventListener("scroll", scheduleViewportUpdate, { passive: true });
addEventListener("resize", scheduleViewportUpdate, { passive: true });
addEventListener("pageshow", scheduleViewportUpdate);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) comparisons.forEach(comparison => comparison.pause());
  else scheduleViewportUpdate();
});
if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(scheduleViewportUpdate, { rootMargin: "180px" });
  comparisons.forEach(comparison => observer.observe(comparison.grid));
}
scheduleViewportUpdate();

const citation = `@misc{zheng2026codeguided,
  title = {Code-Guided Video Editing with Source-Grounded Executable Proxies},
  author = {Zheng, Yuanhong},
  year = {2026},
  note = {Technical report},
  url = {https://yuanhong-zheng.github.io/code-guided-video-editing/}
}`;
let toastTimer;
function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
}

document.getElementById("copy-citation").addEventListener("click", async () => {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(citation);
    else {
      const field = document.createElement("textarea");
      field.value = citation;
      field.style.cssText = "position:fixed;left:-9999px;top:0";
      document.body.append(field);
      field.select();
      const copied = document.execCommand("copy");
      field.remove();
      if (!copied) throw new Error("Clipboard unavailable");
    }
    showToast(messages.clipboardSuccess);
  } catch {
    showToast(messages.clipboardError);
  }
});
