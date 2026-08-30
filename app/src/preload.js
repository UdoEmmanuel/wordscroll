const { contextBridge, ipcRenderer } = require("electron");

// Bridges the application menu (main process) to renderer.js/panels.js/
// theme.js functions, without granting the renderer process Node access
// (contextIsolation stays on). The menu sends an action name; renderer.js
// maps it to the same functions/buttons the existing hotkeys already use.
contextBridge.exposeInMainWorld("menuAPI", {
  onAction: (callback) => {
    ipcRenderer.on("menu-action", (_event, action) => callback(action));
  },
});

// Check-and-notify update banner (see main.js's checkForUpdates()) — the
// renderer only ever learns "a newer version exists" and asks main.js to
// open its GitHub release page in the default browser; it never downloads
// or applies anything itself.
contextBridge.exposeInMainWorld("updateAPI", {
  onUpdateAvailable: (callback) => {
    ipcRenderer.on("update-available", (_event, info) => callback(info));
  },
  openReleasePage: (url) => ipcRenderer.send("open-update-page", url),
});
