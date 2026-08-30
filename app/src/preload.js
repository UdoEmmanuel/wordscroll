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
