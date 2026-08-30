// Phase 2: Display Theme settings modal. Loaded after renderer.js/panels.js/
// hotkeys.js and reuses BACKEND_HTTP/showError — same flat-script,
// shared-global-scope convention as the rest of this app.

const themeModal = document.getElementById("theme-modal");
const themeOpenBtn = document.getElementById("theme-open-btn");
const themeCloseBtn = document.getElementById("theme-close-btn");
const themeApplyBtn = document.getElementById("theme-apply-btn");
const themeResetBtn = document.getElementById("theme-reset-btn");
const themePreviewFrame = document.getElementById("theme-preview");
const themePreviewContainer = document.getElementById("theme-preview-frame");
const rescaleThemePreview = mountScaledPreview(themePreviewContainer, themePreviewFrame);

const themeFontSelect = document.getElementById("theme-font");
const themeVerseColor = document.getElementById("theme-verse-color");
const themeRefColor = document.getElementById("theme-ref-color");
const themeVerseSize = document.getElementById("theme-verse-size");
const themeVerseSizeReadout = document.getElementById("theme-verse-size-readout");
const themeRefSize = document.getElementById("theme-ref-size");
const themeRefSizeReadout = document.getElementById("theme-ref-size-readout");
const themeVerseMarginX = document.getElementById("theme-verse-margin-x");
const themeVerseMarginXReadout = document.getElementById("theme-verse-margin-x-readout");
const themeVerseMarginY = document.getElementById("theme-verse-margin-y");
const themeVerseMarginYReadout = document.getElementById("theme-verse-margin-y-readout");
const themeRefMargin = document.getElementById("theme-ref-margin");
const themeRefMarginReadout = document.getElementById("theme-ref-margin-readout");
const themeBgColorRow = document.getElementById("theme-bg-color-row");
const themeBgColor = document.getElementById("theme-bg-color");
const themeBgOpacityRow = document.getElementById("theme-bg-opacity-row");
const themeBgOpacity = document.getElementById("theme-bg-opacity");
const themeBgOpacityReadout = document.getElementById("theme-bg-opacity-readout");
const themeBgImageRow = document.getElementById("theme-bg-image-row");
const themeBgImageInput = document.getElementById("theme-bg-image-input");
const themeBgImageRemoveBtn = document.getElementById("theme-bg-image-remove-btn");
const themeBgImageThumb = document.getElementById("theme-bg-image-thumb");
const themeShadowSelect = document.getElementById("theme-shadow");
const themeTemplatesGallery = document.getElementById("theme-templates-gallery");
const themeTemplateNameInput = document.getElementById("theme-template-name");
const themeSaveTemplateBtn = document.getElementById("theme-save-template-btn");

const PREVIEW_ORIGIN = "http://127.0.0.1:8765";

// key -> {cssFamily, cssWeight}, fetched from GET /theme/fonts so this file
// never hardcodes its own copy of the backend's font registry.
let fontCssMap = {};
// key -> {maxWidthFraction, maxHeightFraction, paddingMultiplier, marginFraction},
// fetched from GET /theme/layouts — same "backend is the source of truth" pattern.
let layoutMap = {};
// Set by the upload/remove handlers; read into backgroundImage on
// formToThemePatch(). "" means "clear" (sent through to the backend as the
// clear sentinel); null means "no change from whatever's already stored".
let pendingBackgroundImage = null;
// Snapshot of the last loaded/applied theme, for the Apply dirty-state
// indicator (item 6).
let lastAppliedTheme = null;

function radioValue(name) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : null;
}

function setRadioValue(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (input) input.checked = true;
}

function updateBgRowsVisibility() {
  const style = radioValue("theme-bg-style");
  themeBgColorRow.hidden = style !== "box";
  themeBgOpacityRow.hidden = style === "none";
  themeBgImageRow.hidden = style !== "image";
}

function hexToRgba(hex, opacity) {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function themesEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function updateApplyButtonState() {
  const dirty = !lastAppliedTheme || !themesEqual(formToThemePatch(), lastAppliedTheme);
  themeApplyBtn.disabled = !dirty;
  themeApplyBtn.textContent = dirty ? "Apply" : "Applied";
}

// Turns a raw theme dict (either the live form's values, via
// formToThemePatch(), or a saved template's tpl.theme — same shape either
// way, both being a full theme_store.py record) into the derived form
// overlay.js expects from theme-preview postMessage/GET /theme. Shared by
// the live editing preview (sendLivePreview) and the read-only template
// gallery thumbnails (renderTemplateCards), so a template preview renders
// pixel-identical to what Apply would actually produce.
function deriveOverlayTheme(patch) {
  const fontInfo = fontCssMap[patch.fontFamily] || { cssFamily: "'Segoe UI', system-ui, sans-serif", cssWeight: 700 };
  const layoutInfo = layoutMap[patch.layout] || {
    maxWidthFraction: 0.78,
    maxHeightFraction: 0.42,
    paddingMultiplier: 1.0,
    marginFraction: 0.08,
    fontBoost: 1.0,
    fullBleed: false,
  };
  return {
    ...patch,
    _fontCss: fontInfo.cssFamily,
    _fontWeight: fontInfo.cssWeight,
    _bgRgba: hexToRgba(patch.backgroundColor, patch.backgroundOpacity),
    _scrimRgba: `rgba(0, 0, 0, ${patch.backgroundOpacity})`,
    _bgImageUrl: patch.backgroundImage ? `${PREVIEW_ORIGIN}/theme-assets/${patch.backgroundImage}` : null,
    _layoutMaxWidthFraction: layoutInfo.maxWidthFraction,
    _layoutMaxHeightFraction: layoutInfo.maxHeightFraction,
    _layoutPaddingMultiplier: layoutInfo.paddingMultiplier,
    _layoutMarginFraction: layoutInfo.marginFraction,
    _layoutFontBoost: layoutInfo.fontBoost,
    _layoutFullBleed: layoutInfo.fullBleed,
  };
}

// Sent on every input tick while the operator is still adjusting a control —
// applied directly inside the preview iframe via postMessage, no network
// round-trip and nothing persisted/broadcast to the real overlay. Only
// Apply (POST /theme) does that.
function sendLivePreview() {
  const previewTheme = deriveOverlayTheme(formToThemePatch());
  themePreviewFrame.contentWindow.postMessage({ type: "theme-preview", theme: previewTheme }, PREVIEW_ORIGIN);
  updateApplyButtonState();
}

document.querySelectorAll('input[name="theme-bg-style"]').forEach((input) => {
  input.addEventListener("change", () => {
    updateBgRowsVisibility();
    sendLivePreview();
  });
});

document
  .querySelectorAll(
    'input[name="theme-position"], input[name="theme-align"], input[name="theme-ref-placement"], input[name="theme-layout"]'
  )
  .forEach((input) => {
    input.addEventListener("change", sendLivePreview);
  });

themeVerseSize.addEventListener("input", () => {
  themeVerseSizeReadout.textContent = `${themeVerseSize.value}px`;
  sendLivePreview();
});
themeRefSize.addEventListener("input", () => {
  themeRefSizeReadout.textContent = `${themeRefSize.value}px`;
  sendLivePreview();
});
themeVerseMarginX.addEventListener("input", () => {
  themeVerseMarginXReadout.textContent = `${themeVerseMarginX.value}px`;
  sendLivePreview();
});
themeVerseMarginY.addEventListener("input", () => {
  themeVerseMarginYReadout.textContent = `${themeVerseMarginY.value}px`;
  sendLivePreview();
});
themeRefMargin.addEventListener("input", () => {
  themeRefMarginReadout.textContent = `${themeRefMargin.value}px`;
  sendLivePreview();
});
themeBgOpacity.addEventListener("input", () => {
  themeBgOpacityReadout.textContent = `${themeBgOpacity.value}%`;
  sendLivePreview();
});
themeVerseColor.addEventListener("input", sendLivePreview);
themeRefColor.addEventListener("input", sendLivePreview);
themeBgColor.addEventListener("input", sendLivePreview);
themeFontSelect.addEventListener("change", sendLivePreview);
themeShadowSelect.addEventListener("change", sendLivePreview);

themeBgImageInput.addEventListener("change", async () => {
  const file = themeBgImageInput.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme/background-image`, { method: "POST", body: formData });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail || "Could not upload image.");
      return;
    }
    const data = await res.json();
    pendingBackgroundImage = data.filename;
    updateBgImageThumb();
    sendLivePreview();
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
});

themeBgImageRemoveBtn.addEventListener("click", () => {
  pendingBackgroundImage = ""; // clear sentinel
  themeBgImageInput.value = "";
  updateBgImageThumb();
  sendLivePreview();
});

function updateBgImageThumb() {
  if (pendingBackgroundImage) {
    themeBgImageThumb.src = `${BACKEND_HTTP}/theme-assets/${pendingBackgroundImage}`;
    themeBgImageThumb.hidden = false;
  } else {
    themeBgImageThumb.hidden = true;
    themeBgImageThumb.src = "";
  }
}

async function loadThemeFonts() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme/fonts`);
    const data = await res.json();
    themeFontSelect.innerHTML = "";
    fontCssMap = {};
    for (const font of data.fonts) {
      const opt = document.createElement("option");
      opt.value = font.key;
      opt.textContent = font.label;
      themeFontSelect.appendChild(opt);
      fontCssMap[font.key] = { cssFamily: font.cssFamily, cssWeight: font.cssWeight };
    }
  } catch {
    // backend not reachable yet — form will just show an empty dropdown
  }
}

async function loadThemeLayouts() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme/layouts`);
    const data = await res.json();
    layoutMap = data.layouts;
  } catch {
    // backend not reachable yet
  }
}

function populateForm(theme) {
  themeFontSelect.value = theme.fontFamily;
  themeVerseColor.value = theme.verseColor;
  themeRefColor.value = theme.referenceColor;
  themeVerseSize.value = theme.verseFontSize;
  themeVerseSizeReadout.textContent = `${theme.verseFontSize}px`;
  themeRefSize.value = theme.referenceFontSize;
  themeRefSizeReadout.textContent = `${theme.referenceFontSize}px`;
  themeVerseMarginX.value = theme.verseMarginX;
  themeVerseMarginXReadout.textContent = `${theme.verseMarginX}px`;
  themeVerseMarginY.value = theme.verseMarginY;
  themeVerseMarginYReadout.textContent = `${theme.verseMarginY}px`;
  themeRefMargin.value = theme.referenceMargin;
  themeRefMarginReadout.textContent = `${theme.referenceMargin}px`;
  setRadioValue("theme-position", theme.textPosition);
  setRadioValue("theme-align", theme.textAlign);
  setRadioValue("theme-ref-placement", theme.referencePlacement);
  setRadioValue("theme-layout", theme.layout);
  setRadioValue("theme-bg-style", theme.backgroundStyle);
  themeBgColor.value = theme.backgroundColor;
  const opacityPct = Math.round(theme.backgroundOpacity * 100);
  themeBgOpacity.value = opacityPct;
  themeBgOpacityReadout.textContent = `${opacityPct}%`;
  themeShadowSelect.value = theme.shadowIntensity;
  pendingBackgroundImage = theme.backgroundImage || null;
  updateBgImageThumb();
  updateBgRowsVisibility();
  lastAppliedTheme = formToThemePatch();
  updateApplyButtonState();
}

async function loadTheme() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme`);
    const theme = await res.json();
    populateForm(theme);
    sendLivePreview();
  } catch {
    // backend not reachable yet
  }
}

function formToThemePatch() {
  return {
    fontFamily: themeFontSelect.value,
    verseColor: themeVerseColor.value,
    referenceColor: themeRefColor.value,
    verseFontSize: parseInt(themeVerseSize.value, 10),
    referenceFontSize: parseInt(themeRefSize.value, 10),
    verseMarginX: parseInt(themeVerseMarginX.value, 10),
    verseMarginY: parseInt(themeVerseMarginY.value, 10),
    referenceMargin: parseInt(themeRefMargin.value, 10),
    textPosition: radioValue("theme-position"),
    textAlign: radioValue("theme-align"),
    referencePlacement: radioValue("theme-ref-placement"),
    layout: radioValue("theme-layout"),
    backgroundStyle: radioValue("theme-bg-style"),
    backgroundColor: themeBgColor.value,
    backgroundOpacity: parseInt(themeBgOpacity.value, 10) / 100,
    backgroundImage: pendingBackgroundImage,
    shadowIntensity: themeShadowSelect.value,
  };
}

async function applyTheme() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formToThemePatch()),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail ? JSON.stringify(body.detail) : "Could not apply theme.");
      return;
    }
    const theme = await res.json();
    populateForm(theme);
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

async function resetTheme() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme/reset`, { method: "POST" });
    const theme = await res.json();
    populateForm(theme);
    sendLivePreview();
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

// --- Templates gallery ----------------------------------------------------

async function loadTemplates() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme/templates`);
    const data = await res.json();
    renderTemplateCards(data.templates);
  } catch {
    // backend not reachable yet
  }
}

function renderTemplateCards(templates) {
  themeTemplatesGallery.innerHTML = "";
  if (templates.length === 0) {
    const empty = document.createElement("div");
    empty.className = "side-list-empty";
    empty.textContent = "No saved templates yet";
    themeTemplatesGallery.appendChild(empty);
    return;
  }
  for (const tpl of templates) {
    const card = document.createElement("div");
    card.className = "template-card";

    const thumb = document.createElement("div");
    thumb.className = "template-thumb";
    const thumbFrame = document.createElement("iframe");
    thumbFrame.className = "template-thumb-frame";
    thumbFrame.title = `${tpl.name} preview`;
    // ?preview=1 makes overlay.js show a sample verse when nothing is
    // live — exactly what a template swatch needs, with no server-side
    // rendering or screenshot step required. static=1 keeps this thumbnail
    // from subscribing to the live theme WebSocket or the initial /theme
    // fetch (see overlay.js) — without it, applying the form being edited
    // elsewhere in the modal would overwrite every saved template's
    // thumbnail with that unrelated theme, even though the template's own
    // saved data was never touched.
    thumbFrame.src = `${PREVIEW_ORIGIN}/overlay/?preview=1&static=1`;
    const postTemplateTheme = () => {
      if (!thumbFrame.contentWindow) return; // iframe navigated away/destroyed since scheduling
      thumbFrame.contentWindow.postMessage(
        { type: "theme-preview", theme: deriveOverlayTheme(tpl.theme) },
        PREVIEW_ORIGIN
      );
    };
    // Posting once on "load" occasionally races overlay.js's own message
    // listener registration and gets silently dropped (observed directly —
    // not hypothetical), leaving the thumbnail with no theme applied at
    // all. Re-posting a couple more times shortly after is harmless (the
    // same theme applied twice is a no-op) and makes delivery reliable
    // without needing an ack/handshake protocol just for a thumbnail.
    thumbFrame.addEventListener("load", () => {
      postTemplateTheme();
      setTimeout(postTemplateTheme, 150);
      setTimeout(postTemplateTheme, 500);
    });
    thumb.appendChild(thumbFrame);

    const name = document.createElement("div");
    name.className = "template-card-name";
    name.title = tpl.name;
    name.textContent = tpl.name;

    const actions = document.createElement("div");
    actions.className = "template-card-actions";
    const applyBtn = document.createElement("button");
    applyBtn.textContent = "Apply";
    applyBtn.addEventListener("click", () => applyTemplate(tpl.id));
    const deleteBtn = document.createElement("button");
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => deleteTemplate(tpl.id));
    actions.appendChild(applyBtn);
    actions.appendChild(deleteBtn);

    card.appendChild(thumb);
    card.appendChild(name);
    card.appendChild(actions);
    themeTemplatesGallery.appendChild(card);
    // mountScaledPreview reads the container's clientWidth immediately, so
    // it needs to already be attached to the live DOM (not a detached
    // node) — hence this runs after appendChild, not before.
    mountScaledPreview(thumb, thumbFrame);
  }
}

async function applyTemplate(templateId) {
  try {
    const res = await fetch(`${BACKEND_HTTP}/theme/templates/${templateId}/apply`, { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail || "Could not apply template.");
      return;
    }
    const theme = await res.json();
    populateForm(theme);
    sendLivePreview();
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

async function deleteTemplate(templateId) {
  try {
    await fetch(`${BACKEND_HTTP}/theme/templates/${templateId}`, { method: "DELETE" });
    loadTemplates();
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

themeSaveTemplateBtn.addEventListener("click", async () => {
  const name = themeTemplateNameInput.value.trim();
  if (!name) return;
  try {
    await fetch(`${BACKEND_HTTP}/theme/templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    themeTemplateNameInput.value = "";
    loadTemplates();
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
});

// --- Modal open/close ------------------------------------------------------

function openThemeModal() {
  themeModal.hidden = false;
  rescaleThemePreview(); // container was display:none until just now — force a fresh size read
  Promise.all([loadThemeFonts(), loadThemeLayouts()]).then(() => {
    loadTheme();
    loadTemplates();
  });
}

function closeThemeModal() {
  themeModal.hidden = true;
  // Reload the iframe so any un-applied live-preview tweaks are discarded
  // and it reflects the last actually-applied theme next time it opens.
  themePreviewFrame.src = themePreviewFrame.src;
}

themeOpenBtn.addEventListener("click", openThemeModal);
themeCloseBtn.addEventListener("click", closeThemeModal);
themeApplyBtn.addEventListener("click", applyTheme);
themeResetBtn.addEventListener("click", resetTheme);

themeModal.addEventListener("click", (event) => {
  if (event.target === themeModal) closeThemeModal(); // click on the backdrop itself
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !themeModal.hidden) closeThemeModal();
});
