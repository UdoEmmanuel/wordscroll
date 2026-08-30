// Wires the Electron application menu (see main.js's buildMenu()) to the
// same buttons/functions the on-screen controls and hotkeys.js already use,
// via the menuAPI bridge exposed by preload.js. Loaded last so every global
// it touches (startBtn, referenceInput, favoriteCurrent, ...) already exists.
if (window.menuAPI) {
  window.menuAPI.onAction((action) => {
    switch (action) {
      case "start-capture":
        if (!startBtn.disabled) startBtn.click();
        break;
      case "stop-capture":
        if (!stopBtn.disabled) stopBtn.click();
        break;
      case "focus-reference":
        referenceInput.focus();
        referenceInput.select();
        break;
      case "focus-keyword":
        keywordInput.focus();
        keywordInput.select();
        break;
      case "advance-queue":
        if (!queueAdvanceBtn.disabled) advanceQueue();
        break;
      case "favorite-current":
        if (!favoriteCurrentBtn.disabled) favoriteCurrent();
        break;
      case "queue-current":
        if (!queueCurrentBtn.disabled) queueCurrent();
        break;
      case "clear-display":
        if (!clearBtn.disabled) clearBtn.click();
        break;
      case "clear-history":
        historyClearBtn.click();
        break;
      case "open-theme":
        themeOpenBtn.click();
        break;
      case "reload-overlays": {
        // Backend static files are already no-cache (see main.py) and
        // Electron's own disk cache was just cleared by main.js — but
        // re-assigning an iframe's src to the exact same string is a no-op
        // in Chromium, so a cache-busting query param is needed to force
        // the actual re-fetch.
        const bust = (url) => url.split("?")[0] + `?t=${Date.now()}`;
        nowDisplayingFrame.src = bust(nowDisplayingFrame.src);
        const themePreview = document.getElementById("theme-preview");
        if (themePreview) themePreview.src = bust(themePreview.src) + "&preview=1";
        break;
      }
      default:
        break;
    }
  });
}
