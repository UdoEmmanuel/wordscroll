// Phase 2: History / Favorites / Queue panels. Loaded after renderer.js and
// reuses its globals (BACKEND_HTTP, pushToDisplay, showError, referenceLabel,
// currentDisplayState) — same flat-script, shared-global-scope pattern as
// the rest of this app (no bundler, no module system).

const historyList = document.getElementById("history-list");
const favoritesList = document.getElementById("favorites-list");
const queueList = document.getElementById("queue-list");
const historyClearBtn = document.getElementById("history-clear-btn");
const queueAdvanceBtn = document.getElementById("queue-advance-btn");
const favoriteCurrentBtnEl = document.getElementById("favorite-current-btn");
const queueCurrentBtnEl = document.getElementById("queue-current-btn");

let historyEntries = [];
let favoriteEntries = [];
let queueEntries = [];

function emptyRow(list, text) {
  list.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "side-list-empty";
  empty.textContent = text;
  list.appendChild(empty);
}

function displayRequestBody(ref) {
  return {
    book: ref.book,
    chapter: ref.chapter,
    verse_start: ref.verseStart,
    verse_end: ref.verseEnd,
    translation: ref.translation || "KJV",
  };
}

// --- History ----------------------------------------------------------

function renderHistory(entries) {
  historyEntries = entries;
  if (entries.length === 0) {
    emptyRow(historyList, "Nothing displayed yet");
    return;
  }
  historyList.innerHTML = "";
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "side-row";
    row.title = "Click to display this verse again";
    const ref = document.createElement("div");
    ref.className = "side-row-ref";
    ref.textContent = `${entry.reference} (${entry.translation})`;
    row.appendChild(ref);
    row.addEventListener("click", () => pushToDisplay(entry));
    historyList.appendChild(row);
  }
}

async function loadHistory() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/history`);
    const data = await res.json();
    renderHistory(data.history);
  } catch {
    // backend not reachable yet — leave the default empty state
  }
}

historyClearBtn.addEventListener("click", async () => {
  try {
    await fetch(`${BACKEND_HTTP}/history/clear`, { method: "POST" });
    renderHistory([]);
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
});

// --- Favorites ----------------------------------------------------------

function renderFavorites(favorites) {
  favoriteEntries = favorites;
  if (favorites.length === 0) {
    emptyRow(favoritesList, "No favorites yet");
    return;
  }
  favoritesList.innerHTML = "";
  for (const fav of favorites) {
    const row = document.createElement("div");
    row.className = "side-row";
    row.title = "Click to display this verse";
    const ref = document.createElement("div");
    ref.className = "side-row-ref";
    ref.textContent = fav.reference;
    row.appendChild(ref);
    const removeBtn = document.createElement("button");
    removeBtn.className = "side-row-remove";
    removeBtn.textContent = "✕";
    removeBtn.title = "Remove favorite";
    removeBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        const res = await fetch(`${BACKEND_HTTP}/favorites/${fav.id}`, { method: "DELETE" });
        const data = await res.json();
        renderFavorites(data.favorites);
      } catch (err) {
        showError(`Could not reach backend: ${err.message}`);
      }
    });
    row.appendChild(removeBtn);
    row.addEventListener("click", () => pushToDisplay(fav));
    favoritesList.appendChild(row);
  }
}

async function loadFavorites() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/favorites`);
    const data = await res.json();
    renderFavorites(data.favorites);
  } catch {
    // backend not reachable yet
  }
}

async function favoriteCurrent() {
  if (!currentDisplayState) return;
  try {
    const res = await fetch(`${BACKEND_HTTP}/favorites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(displayRequestBody(currentDisplayState)),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail || "Could not favorite this verse.");
      return;
    }
    const data = await res.json();
    renderFavorites(data.favorites);
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

favoriteCurrentBtnEl.addEventListener("click", favoriteCurrent);

// --- Queue ----------------------------------------------------------

function renderQueue(queue) {
  queueEntries = queue;
  queueAdvanceBtn.disabled = queue.length === 0;
  if (queue.length === 0) {
    emptyRow(queueList, "Queue is empty");
    return;
  }
  queueList.innerHTML = "";
  queue.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "side-row";
    row.title = "Click to display this verse";
    const ref = document.createElement("div");
    ref.className = "side-row-ref";
    ref.textContent = item.reference;
    row.appendChild(ref);

    const actions = document.createElement("div");
    actions.className = "side-row-actions";

    const upBtn = document.createElement("button");
    upBtn.className = "side-row-move";
    upBtn.textContent = "↑";
    upBtn.title = "Move up";
    upBtn.disabled = index === 0;
    upBtn.addEventListener("click", (event) => moveQueueItem(event, item.id, "up"));

    const downBtn = document.createElement("button");
    downBtn.className = "side-row-move";
    downBtn.textContent = "↓";
    downBtn.title = "Move down";
    downBtn.disabled = index === queue.length - 1;
    downBtn.addEventListener("click", (event) => moveQueueItem(event, item.id, "down"));

    const removeBtn = document.createElement("button");
    removeBtn.className = "side-row-remove";
    removeBtn.textContent = "✕";
    removeBtn.title = "Remove from queue";
    removeBtn.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        const res = await fetch(`${BACKEND_HTTP}/queue/${item.id}`, { method: "DELETE" });
        const data = await res.json();
        renderQueue(data.queue);
      } catch (err) {
        showError(`Could not reach backend: ${err.message}`);
      }
    });

    actions.appendChild(upBtn);
    actions.appendChild(downBtn);
    actions.appendChild(removeBtn);
    row.appendChild(actions);
    row.addEventListener("click", () => pushToDisplay(item));
    queueList.appendChild(row);
  });
}

async function moveQueueItem(event, itemId, direction) {
  event.stopPropagation();
  try {
    const res = await fetch(`${BACKEND_HTTP}/queue/${itemId}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction }),
    });
    const data = await res.json();
    renderQueue(data.queue);
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

async function loadQueue() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/queue`);
    const data = await res.json();
    renderQueue(data.queue);
  } catch {
    // backend not reachable yet
  }
}

async function queueCurrent() {
  if (!currentDisplayState) return;
  try {
    const res = await fetch(`${BACKEND_HTTP}/queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(displayRequestBody(currentDisplayState)),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showError(body.detail || "Could not add this verse to the queue.");
      return;
    }
    const data = await res.json();
    renderQueue(data.queue);
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

queueCurrentBtnEl.addEventListener("click", queueCurrent);

async function advanceQueue() {
  try {
    const res = await fetch(`${BACKEND_HTTP}/queue/advance`, { method: "POST" });
    if (!res.ok) return; // queue empty — no-op
    applyDisplayState(await res.json());
    loadQueue();
  } catch (err) {
    showError(`Could not reach backend: ${err.message}`);
  }
}

queueAdvanceBtn.addEventListener("click", advanceQueue);

loadHistory();
loadFavorites();
loadQueue();
