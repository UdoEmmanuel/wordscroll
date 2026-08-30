const WS_URL = `ws://${location.host}/ws/transcript`;

// Loaded with ?preview=1 inside the Electron app's Theme settings modal, so
// the operator can see and tune the theme without needing a verse live on
// the real production overlay first. The real overlay (OBS/vMix Browser
// Source, no query param) still hides when nothing is displayed, same as
// always — only the preview iframe falls back to a sample verse.
const isPreview = new URLSearchParams(location.search).get("preview") === "1";
// Loaded with &static=1 by the Theme modal's template gallery thumbnails —
// each one is a fire-and-forget snapshot of one saved template's theme
// (pushed once via postMessage right after load), not a view of whatever's
// currently live. Without this flag every overlay page — thumbnails
// included — opens the same /ws/transcript socket and applies every
// "theme" broadcast same as the real output, so clicking Apply on the form
// being edited was silently overwriting every template thumbnail's preview
// even though the saved template data itself was untouched. Static mode
// skips connect() entirely so nothing after the initial postMessage can
// ever change what a thumbnail shows.
const isStatic = new URLSearchParams(location.search).get("static") === "1";
const SAMPLE_STATE = {
  active: true,
  reference: "John 3:16",
  translation: "KJV",
  text: "For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.",
};

const root = document.getElementById("root");
const bgLayer = document.getElementById("bg-layer");
const verseText = document.getElementById("verse-text");
const verseRef = document.getElementById("verse-ref");

// applyState() (visibility) and applyTheme() (position/align/background/
// shadow classes) both write to #root's className — composed from these two
// pieces so neither call clobbers the other's classes.
let hiddenClass = "hidden";
let themeClasses = "";
let currentTheme = null; // last theme applied, needed by fitVerseText()

function renderRootClass() {
  root.className = [hiddenClass, themeClasses].filter(Boolean).join(" ");
}

function applyState(state) {
  if (!state || !state.active) {
    if (isPreview) {
      state = SAMPLE_STATE; // nothing live — show a sample so theming isn't blocked on it
    } else {
      hiddenClass = "hidden";
      renderRootClass();
      return;
    }
  }
  verseText.textContent = state.text;
  verseRef.textContent = `${state.reference} (${state.translation})`;
  hiddenClass = "";
  renderRootClass();
  fitVerseText(); // new verse text needs its own fit pass, even if theme is unchanged
}

function applyTheme(theme) {
  currentTheme = theme;
  const style = document.documentElement.style;
  style.setProperty("--verse-color", theme.verseColor);
  style.setProperty("--ref-color", theme.referenceColor);
  style.setProperty("--ref-size", `${Math.round(theme.referenceFontSize * theme._layoutFontBoost)}px`);
  style.setProperty("--font-family", theme._fontCss);
  style.setProperty("--font-weight", theme._fontWeight);
  style.setProperty("--bg-color", theme._bgRgba);
  style.setProperty("--bg-image-url", theme._bgImageUrl ? `url("${theme._bgImageUrl}")` : "none");
  style.setProperty("--scrim-rgba", theme._scrimRgba);
  style.setProperty("--frame-margin", `${theme._layoutMarginFraction * 100}%`);
  style.setProperty("--fit-max-width", `${theme._layoutMaxWidthFraction * 100}vw`);
  style.setProperty("--reference-margin", `${theme.referenceMargin}px`);
  const boxPadX = Math.round(theme.verseMarginX * theme._layoutPaddingMultiplier);
  const boxPadY = Math.round(theme.verseMarginY * theme._layoutPaddingMultiplier);
  style.setProperty("--box-pad-x", `${boxPadX}px`);
  style.setProperty("--box-pad-y", `${boxPadY}px`);

  // Full-bleed layouts ("Full Frame") show their background on the
  // separate #bg-layer (spans the whole canvas); non-full-bleed layouts
  // ("Lower Third") keep it on #root itself (hugs the text). Never both —
  // only one of bg-box/bg-image (on #root) or #bg-layer's classes is active
  // at a time, based on _layoutFullBleed.
  const fullBleed = !!theme._layoutFullBleed;
  const bgActive = theme.backgroundStyle !== "none";

  bgLayer.className = [
    fullBleed && bgActive ? "active" : "",
    fullBleed ? "fullbleed" : "",
    theme.backgroundStyle === "box" ? "style-box" : "",
    theme.backgroundStyle === "image" ? "style-image" : "",
  ]
    .filter(Boolean)
    .join(" ");

  themeClasses = [
    `pos-${theme.textPosition}`,
    `align-${theme.textAlign}`,
    !fullBleed && theme.backgroundStyle === "box" ? "bg-box" : "",
    !fullBleed && theme.backgroundStyle === "image" ? "bg-image" : "",
    theme.referencePlacement === "above" ? "ref-above" : "",
    `shadow-${theme.shadowIntensity}`,
    isPreview ? "show-guides" : "", // dashed margin guides — only in the theme modal's preview, never the real output
  ]
    .filter(Boolean)
    .join(" ");
  renderRootClass();
  fitVerseText();
}

// Client-side equivalent of display_renderer.py's _fit_verse_font(): the
// verse text's max-width already comes from CSS (--fit-max-width, so the
// browser wraps it naturally); this loop only needs to shrink --verse-size
// until the wrapped block's height fits the target box, since CSS has no
// native "shrink multi-line text to fit a height" primitive. Cheap — only
// runs on a display or theme change, not per animation frame.
const AUTO_FIT_MIN = 16;
const AUTO_FIT_STEP = 2;

function fitVerseText() {
  if (!currentTheme) return;
  const maxSize = Math.round(currentTheme.verseFontSize * currentTheme._layoutFontBoost);
  const maxHeightPx =
    (currentTheme._layoutMaxHeightFraction * window.innerHeight) -
    2 * Math.round(currentTheme.verseMarginY * currentTheme._layoutPaddingMultiplier) -
    currentTheme.referenceMargin -
    (verseRef.offsetHeight || currentTheme.referenceFontSize * currentTheme._layoutFontBoost * 1.35);

  let size = maxSize;
  document.documentElement.style.setProperty("--verse-size", `${size}px`);
  while (verseText.scrollHeight > maxHeightPx && size > AUTO_FIT_MIN) {
    size -= AUTO_FIT_STEP;
    document.documentElement.style.setProperty("--verse-size", `${size}px`);
  }
}

// Pick up whatever's already live/themed in case this overlay connects
// mid-service. Kept even in static mode (template gallery thumbnails) —
// isPreview's SAMPLE_STATE fallback still needs applyState() to run once to
// un-hide #root and render the sample verse text.
fetch(`http://${location.host}/display/state`)
  .then((r) => r.json())
  .then(applyState)
  .catch(() => {});

// Skipped in static mode: a thumbnail's only theme should ever be the one
// postMessage it receives right after load (see below). This fetch is
// async and can resolve *after* that postMessage — since network timing
// isn't guaranteed relative to the load event a parent's postMessage fires
// on, it would silently overwrite the correct template preview with
// whatever theme happens to be really persisted right now. That race (not
// the live WebSocket broadcast, which static mode already skips via
// connect() below) was the actual remaining cause of a template thumbnail
// flipping to the currently-being-edited theme after Apply.
if (!isStatic) {
  fetch(`http://${location.host}/theme`)
    .then((r) => r.json())
    .then(applyTheme)
    .catch(() => {});
}

// Live preview: theme.js posts a draft theme on every slider/color-picker
// tick while the operator is still adjusting — applied immediately with no
// network round-trip, and never persisted/broadcast (only Apply does that).
// Restricted to preview mode and to messages actually from the parent frame
// (this iframe's direct embedder), not just any origin.
if (isPreview) {
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    if (event.data && event.data.type === "theme-preview") applyTheme(event.data.theme);
  });
}

function connect() {
  const ws = new WebSocket(WS_URL);
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "display") applyState(msg);
    else if (msg.type === "theme") applyTheme(msg.theme);
  };
  ws.onclose = () => {
    setTimeout(connect, 1000); // OBS/vMix sources should self-heal after a backend restart
  };
  ws.onerror = () => ws.close();
}

if (!isStatic) connect();
