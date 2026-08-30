const BACKEND_HTTP = "http://127.0.0.1:8765";
const BACKEND_WS = "ws://127.0.0.1:8765/ws/transcript";

// The overlay renders in absolute px matching the NDI canvas (1920x1080,
// see backend/display_renderer.py). Any preview iframe that just sits in a
// smaller on-screen box (e.g. 640px wide) would show those px sizes
// hugely oversized relative to what a real 1920-wide OBS Browser Source
// shows — the same theme would look completely different in the preview
// vs. the real output. Fix: force the iframe to actually render at the
// full 1920x1080 canvas size, then CSS-scale the whole thing down to fit
// its visible container — so proportions always match the real output
// exactly, at any preview size.
const OVERLAY_CANVAS_WIDTH = 1920;
const OVERLAY_CANVAS_HEIGHT = 1080;

function mountScaledPreview(container, iframe) {
  iframe.style.width = `${OVERLAY_CANVAS_WIDTH}px`;
  iframe.style.height = `${OVERLAY_CANVAS_HEIGHT}px`;
  iframe.style.border = "none";
  iframe.style.display = "block";
  iframe.style.transformOrigin = "top left";

  function rescale() {
    const scale = container.clientWidth / OVERLAY_CANVAS_WIDTH;
    iframe.style.transform = `scale(${scale})`;
    container.style.height = `${OVERLAY_CANVAS_HEIGHT * scale}px`;
  }

  new ResizeObserver(rescale).observe(container);
  rescale();
  return rescale; // callers can force a recompute (e.g. right after unhiding a modal)
}

const deviceSelect = document.getElementById("device-select");
const rescanBtn = document.getElementById("rescan-btn");
const startBtn = document.getElementById("start-btn");
const stopBtn = document.getElementById("stop-btn");
const connStatus = document.getElementById("conn-status");
const finalLog = document.getElementById("final-log");
const partialLine = document.getElementById("partial-line");
const errorBanner = document.getElementById("error-banner");
const micIconFill = document.getElementById("mic-icon-fill");
const referenceLog = document.getElementById("reference-log");
const pendingLog = document.getElementById("pending-log");
const clearBtn = document.getElementById("clear-btn");
const nowDisplayingPreview = document.getElementById("now-displaying-preview");
const nowDisplayingFrame = document.getElementById("now-displaying-frame");
const chapterNavList = document.getElementById("chapter-nav-list");
const favoriteCurrentBtn = document.getElementById("favorite-current-btn");
const queueCurrentBtn = document.getElementById("queue-current-btn");

mountScaledPreview(nowDisplayingPreview, nowDisplayingFrame);

// What's currently on screen, or null — read by panels.js (Favorite/Queue
// current) and hotkeys.js (F/Q hotkeys) so they don't need their own copy.
// The actual visual (what's on screen) is the embedded live overlay iframe
// above — it already updates itself over the same WebSocket, independent
// of this function, which now only tracks state for the action buttons and
// the Chapter Navigator.
let currentDisplayState = null;

function applyDisplayState(state) {
  currentDisplayState = state && state.active ? state : null;
  if (!state || !state.active) {
    clearBtn.disabled = true;
    favoriteCurrentBtn.disabled = true;
    queueCurrentBtn.disabled = true;
    renderChapterNav(null, null, null);
    return;
  }
  clearBtn.disabled = false;
  favoriteCurrentBtn.disabled = false;
  queueCurrentBtn.disabled = false;
  loadChapterNav(state.book, state.chapter, state.verseStart);
}

// Milestone 6 (chapter navigator): jump to any verse in whatever's currently
// displayed without retyping a search — works for a verse that got on
// screen any way (voice, search, next/previous, another chapter-nav click).
let chapterNavKey = null; // `${book}|${chapter}` — skip refetching if unchanged

async function loadChapterNav(book, chapter, currentVerse) {
  const key = `${book}|${chapter}`;
  if (key === chapterNavKey) {
    highlightChapterNavRow(currentVerse);
    return;
  }
  chapterNavKey = key;
  try {
    const res = await fetch(`${BACKEND_HTTP}/chapter?book=${encodeURIComponent(book)}&chapter=${chapter}`);
    if (!res.ok) {
      renderChapterNav(null, null, null);
      return;
    }
    const data = await res.json();
    renderChapterNav(book, chapter, currentVerse, data.verses);
  } catch {
    renderChapterNav(null, null, null);
  }
}

function renderChapterNav(book, chapter, currentVerse, verses) {
  chapterNavList.innerHTML = "";
  if (!book || !verses) {
    chapterNavKey = null;
    const empty = document.createElement("div");
    empty.className = "chapter-nav-empty";
    empty.textContent = "Display a verse to browse its chapter";
    chapterNavList.appendChild(empty);
    return;
  }
  for (const v of verses) {
    const row = document.createElement("div");
    row.className = "chapter-nav-row";
    row.dataset.verse = v.verse;
    if (v.verse === currentVerse) row.classList.add("current");
    const num = document.createElement("span");
    num.className = "cn-verse";
    num.textContent = v.verse;
    const text = document.createElement("span");
    text.className = "cn-text";
    text.textContent = v.text;
    row.appendChild(num);
    row.appendChild(text);
    row.addEventListener("click", () => {
      pushToDisplay({ book, chapter, verseStart: v.verse, verseEnd: null });
    });
    chapterNavList.appendChild(row);
  }
  highlightChapterNavRow(currentVerse);
}

function highlightChapterNavRow(currentVerse) {
  for (const row of chapterNavList.querySelectorAll(".chapter-nav-row")) {
    const isCurrent = Number(row.dataset.verse) === currentVerse;
    row.classList.toggle("current", isCurrent);
    if (isCurrent) row.scrollIntoView({ block: "nearest" });
  }
}

async function pushToDisplay(ref) {
  try {
    const res = await fetch(`${BACKEND_HTTP}/display/push`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        book: ref.book,
        chapter: ref.chapter,
        verse_start: ref.verseStart,
        verse_end: ref.verseEnd,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail || `Could not display ${referenceLabel(ref)}.`);
      return;
    }
    applyDisplayState(await res.json());
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

clearBtn.addEventListener("click", async () => {
  try {
    const res = await fetch(`${BACKEND_HTTP}/display/clear`, { method: "POST" });
    applyDisplayState(await res.json());
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
});

// Manual counterpart to the spoken "next verse" command — both call the same
// backend advance logic, so voice and hotkey are fully interchangeable.
async function advanceVerse() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/display/next`, { method: "POST" });
    if (!res.ok) return; // nothing displayed yet, or no verse number to advance from — no-op
    applyDisplayState(await res.json());
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

async function retreatVerse() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/display/previous`, { method: "POST" });
    if (!res.ok) return; // nothing displayed, at verse 1, or no verse number — no-op
    applyDisplayState(await res.json());
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

// Keyboard shortcuts (arrow keys, F5/F6, and the Phase 2 letter hotkeys) all
// live together in hotkeys.js now, loaded after this file.

function referenceLabel(ref) {
  let label = `${ref.book} ${ref.chapter}`;
  if (ref.verseStart != null) {
    label += `:${ref.verseStart}`;
    if (ref.verseEnd != null) label += `-${ref.verseEnd}`;
  }
  return label;
}

// While one utterance is still in progress, whisper re-transcribes it every
// ~1.5s and the detector re-runs on the growing text — "John 3" can appear
// before "verse 16" is spoken. Rather than spawning a new card each time
// (which left stale, incomplete cards clickable), we update a single
// in-progress card (in the Detected References log) in place and only
// "lock it in" once a final segment confirms it — at which point it either
// stays there (high confidence, already auto-displayed) or moves to the
// Pending Suggestions panel for the operator to approve/dismiss (low
// confidence — includes recitation matches, which are always low).
let liveCard = null;

// Cards show the actual bundled scripture text as the main excerpt (not
// what was heard/said) — that's what the operator needs to judge a match,
// especially the low-confidence ones. What was heard stays as a smaller
// secondary caption for context on *why* it matched.
function cardBodyHtml() {
  return '<div class="ref-title"></div><div class="ref-preview"></div><div class="ref-raw"></div>';
}

function fillCardBody(card, ref, note) {
  card.querySelector(".ref-title").textContent = referenceLabel(ref);
  card.querySelector(".ref-preview").textContent = ref.previewText || "";
  card.querySelector(".ref-raw").textContent = `You said: "${ref.rawText}"${note}`;
}

function fillLiveCard(ref, segmentType) {
  if (!liveCard) {
    liveCard = document.createElement("div");
    liveCard.className = "reference-card reference-card-live";
    liveCard.title = "Click to display this reference";
    liveCard.innerHTML = cardBodyHtml();
    referenceLog.appendChild(liveCard);
  }
  fillCardBody(liveCard, ref, " (live)");
  liveCard.onclick = () => pushToDisplay(ref);
  referenceLog.scrollTop = referenceLog.scrollHeight;
}

function addHighConfidenceCard(ref) {
  const card = liveCard || document.createElement("div");
  if (!liveCard) {
    card.title = "Click to display this reference";
    card.innerHTML = cardBodyHtml();
    referenceLog.appendChild(card);
  }
  card.className = "reference-card";
  fillCardBody(card, ref, " (auto-displayed)");
  card.onclick = () => pushToDisplay(ref);
  referenceLog.scrollTop = referenceLog.scrollHeight;
}

function addPendingCard(ref) {
  if (liveCard) {
    liveCard.remove(); // the in-progress preview belongs to Detected References, not here
  }
  const card = document.createElement("div");
  card.className = "pending-card";
  card.innerHTML = cardBodyHtml();
  fillCardBody(card, ref, "");
  const actions = document.createElement("div");
  actions.className = "pending-card-actions";
  const approveBtn = document.createElement("button");
  approveBtn.className = "approve-btn";
  approveBtn.textContent = "Approve";
  approveBtn.onclick = () => {
    pushToDisplay(ref);
    card.remove();
  };
  const dismissBtn = document.createElement("button");
  dismissBtn.className = "dismiss-btn";
  dismissBtn.textContent = "Dismiss";
  dismissBtn.onclick = () => card.remove();
  actions.appendChild(approveBtn);
  actions.appendChild(dismissBtn);
  card.appendChild(actions);
  pendingLog.appendChild(card);
  pendingLog.scrollTop = pendingLog.scrollHeight;
}

function renderReferences(refs, segmentType) {
  for (const ref of refs) {
    if (segmentType === "partial") {
      fillLiveCard(ref, segmentType);
    } else if (ref.confidence === "high") {
      addHighConfidenceCard(ref);
      liveCard = null;
    } else {
      addPendingCard(ref);
      liveCard = null;
    }
  }
}

// RMS of typical speech at a normal mic gain rarely exceeds ~0.15-0.2;
// scale so a normal speaking voice fills most of the icon.
function setMeterLevel(rms) {
  const pct = Math.min(100, Math.max(0, (rms / 0.2) * 100));
  micIconFill.style.clipPath = `inset(${100 - pct}% 0 0 0)`;
}

let ws = null;

function setConnStatus(online) {
  connStatus.textContent = online ? "Online" : "Offline";
  connStatus.className = `status ${online ? "status-online" : "status-offline"}`;
}

let devicesAvailable = false;
let modelReady = false;

function refreshStartEnabled() {
  if (stopBtn.disabled === false) return; // don't touch Start while capturing
  startBtn.disabled = !(devicesAvailable && modelReady);
  startBtn.title = modelReady
    ? "Start"
    : "Loading speech model… (first run downloads it, can take a minute)";
}

// Live refresh: re-fetches every few seconds so plugging in a new input
// device updates the dropdown without restarting the app. Device *index*
// can shift when devices connect/disconnect, so the current selection is
// tracked and restored by name, not index. Skipped entirely while
// capturing (the dropdown is locked/disabled then anyway) and skipped when
// nothing actually changed, to avoid needless DOM churn.
let lastDeviceListSignature = null;

async function loadDevices() {
  if (!stopBtn.disabled) return; // currently capturing — leave the locked dropdown alone
  try {
    const res = await fetch(`${BACKEND_HTTP}/devices`);
    const data = await res.json();
    const signature = data.devices.map((d) => d.name).join("|");
    if (signature !== lastDeviceListSignature) {
      lastDeviceListSignature = signature;
      const previousName = deviceSelect.selectedOptions[0]?.dataset.name || null;
      deviceSelect.innerHTML = "";
      for (const dev of data.devices) {
        const opt = document.createElement("option");
        opt.value = dev.index;
        opt.dataset.name = dev.name;
        opt.textContent = dev.is_default ? `${dev.name} (default)` : dev.name;
        deviceSelect.appendChild(opt);
      }
      if (previousName) {
        const match = Array.from(deviceSelect.options).find((o) => o.dataset.name === previousName);
        if (match) deviceSelect.value = match.value;
      }
    }
    setConnStatus(true);
    devicesAvailable = data.devices.length > 0;
    refreshStartEnabled();
  } catch (err) {
    setConnStatus(false);
    devicesAvailable = false;
    refreshStartEnabled();
    console.error("Failed to load devices — is the backend running?", err);
  }
}

setInterval(loadDevices, 3000);

// Manual rescan alongside the automatic poll (not a replacement for it) —
// loadDevices() already no-ops while capturing, but the button itself is
// also disabled then (kept in sync with deviceSelect.disabled below) so
// clicking it doesn't silently do nothing.
rescanBtn.addEventListener("click", () => loadDevices());

async function pollModelReady() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/status`);
    const data = await res.json();
    modelReady = !!data.model_ready;
  } catch {
    modelReady = false;
  }
  refreshStartEnabled();
  if (!modelReady) {
    setTimeout(pollModelReady, 1000);
  }
}

// Connected from app boot (not gated behind Start/audio capture) — display,
// history, favorites, and queue changes all broadcast over this same socket
// regardless of whether audio capture is running (e.g. pure manual search),
// so the UI needs to stay connected the whole time to catch them.
function connectWebSocket() {
  ws = new WebSocket(BACKEND_WS);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "final") {
      const line = document.createElement("div");
      line.className = "line";
      line.textContent = msg.text;
      finalLog.appendChild(line);
      finalLog.scrollTop = finalLog.scrollHeight;
      partialLine.textContent = "";
    } else if (msg.type === "partial") {
      partialLine.textContent = msg.text;
    } else if (msg.type === "level") {
      setMeterLevel(msg.level);
    } else if (msg.type === "reference") {
      renderReferences(msg.references, msg.segmentType);
    } else if (msg.type === "display") {
      applyDisplayState(msg);
    } else if (msg.type === "history_add") {
      renderHistory([msg.entry, ...historyEntries]);
    } else if (msg.type === "history_cleared") {
      renderHistory([]);
    } else if (msg.type === "favorites") {
      renderFavorites(msg.favorites);
    } else if (msg.type === "queue") {
      renderQueue(msg.queue);
    }
  };

  ws.onclose = () => {
    ws = null;
    setMeterLevel(0);
    setTimeout(connectWebSocket, 2000); // backend restarted or briefly unreachable — keep retrying
  };
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function clearError() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

startBtn.addEventListener("click", async () => {
  clearError();
  const deviceIndex = parseInt(deviceSelect.value, 10);
  startBtn.disabled = true;
  deviceSelect.disabled = true;
  rescanBtn.disabled = true;
  startBtn.title = "Starting…";

  let res;
  try {
    res = await fetch(`${BACKEND_HTTP}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_index: deviceIndex }),
    });
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
    deviceSelect.disabled = false;
    rescanBtn.disabled = false;
    refreshStartEnabled();
    return;
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    showError(body.detail || `Failed to start (HTTP ${res.status}). Try a different audio device.`);
    deviceSelect.disabled = false;
    rescanBtn.disabled = false;
    refreshStartEnabled();
    return;
  }

  startBtn.title = "Start";
  stopBtn.disabled = false;
});

stopBtn.addEventListener("click", async () => {
  await fetch(`${BACKEND_HTTP}/stop`, { method: "POST" });
  // WebSocket stays open — history/favorites/queue broadcasts still need it
  // even when audio capture isn't running.
  setMeterLevel(0);
  liveCard = null;
  stopBtn.disabled = true;
  deviceSelect.disabled = false;
  rescanBtn.disabled = false;
  refreshStartEnabled();
});

async function loadDisplayState() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/display/state`);
    applyDisplayState(await res.json());
  } catch {
    // backend not reachable yet — leave the default "Nothing on screen" state
  }
}

// --- Milestone 4: manual reference/keyword search -------------------------
// FR-6.1/6.2: works regardless of whether audio capture is running, and
// bypasses detection entirely — search results push straight to display.
// Two independent fields (not a shared input + mode toggle) so the operator
// can jump straight to either one via F5/F6 without an extra click.

const referenceInput = document.getElementById("search-input-reference");
const keywordInput = document.getElementById("search-input-keyword");
const searchStatus = document.getElementById("search-status");
const searchResultsList = document.getElementById("search-results-list");

let searchRequestId = 0;
const debounceTimers = { reference: null, keyword: null };
let lastReferenceResults = [];

function renderSearchResults(results, mode) {
  if (mode === "reference") lastReferenceResults = results;
  searchResultsList.innerHTML = "";
  if (results.length === 0) {
    const empty = document.createElement("div");
    empty.className = "search-no-results";
    empty.textContent = "No results";
    searchResultsList.appendChild(empty);
    return;
  }
  for (const r of results) {
    const card = document.createElement("div");
    card.className = "search-result";
    card.title = "Click to display this verse";
    const ref = document.createElement("div");
    ref.className = "sr-ref";
    ref.textContent = r.reference;
    const text = document.createElement("div");
    text.className = "sr-text";
    text.textContent = r.text;
    card.appendChild(ref);
    card.appendChild(text);
    card.addEventListener("click", () => {
      pushToDisplay({ book: r.book, chapter: r.chapter, verseStart: r.verseStart, verseEnd: r.verseEnd });
    });
    searchResultsList.appendChild(card);
  }
}

async function runSearch(mode) {
  const input = mode === "reference" ? referenceInput : keywordInput;
  const query = input.value.trim();
  const thisRequestId = ++searchRequestId;

  if (!query) {
    searchStatus.textContent = "";
    searchResultsList.innerHTML = "";
    return;
  }
  if (mode === "keyword" && query.length < 3) {
    searchStatus.textContent = "Type 3+ characters";
    searchResultsList.innerHTML = "";
    return;
  }

  searchStatus.textContent = "Searching…";
  const endpoint = mode === "reference" ? "/search/reference" : "/search/keyword";
  try {
    const res = await fetch(`${BACKEND_HTTP}${endpoint}?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (thisRequestId !== searchRequestId) return; // a newer keystroke superseded this request
    searchStatus.textContent = data.results.length ? `${data.results.length} result(s)` : "No results";
    renderSearchResults(data.results, mode);
  } catch (err) {
    if (thisRequestId !== searchRequestId) return;
    searchStatus.textContent = "Backend unreachable";
  }
}

// Enter once -> search (same as typing). Enter again within this window ->
// push the top reference result live, hands-free, no mouse needed.
const DOUBLE_ENTER_WINDOW_MS = 700;
let lastReferenceEnterAt = 0;

function wireSearchField(input, mode) {
  input.addEventListener("input", () => {
    clearTimeout(debounceTimers[mode]);
    debounceTimers[mode] = setTimeout(() => runSearch(mode), 250);
  });
  input.addEventListener("keydown", (event) => {
    // Let arrow keys navigate text in the field instead of triggering the
    // next/previous-verse hotkeys while the operator is typing.
    event.stopPropagation();
    if (event.key === "Escape") {
      input.value = "";
      runSearch(mode);
      input.blur();
    } else if (event.key === "Enter") {
      clearTimeout(debounceTimers[mode]);
      if (mode === "reference") {
        const now = Date.now();
        if (now - lastReferenceEnterAt < DOUBLE_ENTER_WINDOW_MS && lastReferenceResults.length > 0) {
          const r = lastReferenceResults[0];
          pushToDisplay({ book: r.book, chapter: r.chapter, verseStart: r.verseStart, verseEnd: r.verseEnd });
          lastReferenceEnterAt = 0; // don't let a third Enter re-push immediately
          input.blur(); // frees the arrow keys back to verse navigation without a manual click-out
          return;
        }
        lastReferenceEnterAt = now;
      }
      runSearch(mode);
    }
  });
}

wireSearchField(referenceInput, "reference");
wireSearchField(keywordInput, "keyword");

loadDevices();
pollModelReady();
loadDisplayState();
connectWebSocket();
// loadHistory()/loadFavorites()/loadQueue() are called from panels.js
// (loaded after this file, which is where those functions are defined).
