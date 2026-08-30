// Check-and-notify update banner (see main.js's checkForUpdates()). Purely
// informational: main.js already decided a newer version exists by the
// time this listener fires, so this file only ever displays that and hands
// off to the browser — it never downloads or applies anything itself.
const updateBanner = document.getElementById("update-banner");
const updateBannerText = document.getElementById("update-banner-text");
const updateViewBtn = document.getElementById("update-view-btn");
const updateDismissBtn = document.getElementById("update-dismiss-btn");

let pendingUpdateUrl = null;

if (window.updateAPI) {
  window.updateAPI.onUpdateAvailable((info) => {
    pendingUpdateUrl = info.url;
    updateBannerText.textContent = `A new version (${info.version}) is available.`;
    updateBanner.hidden = false;
  });
}

updateViewBtn.addEventListener("click", () => {
  if (pendingUpdateUrl) window.updateAPI.openReleasePage(pendingUpdateUrl);
});

updateDismissBtn.addEventListener("click", () => {
  updateBanner.hidden = true;
});
