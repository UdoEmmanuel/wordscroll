const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");
const packageJson = require("../package.json");

const BACKEND_DIR = path.join(__dirname, "..", "..", "backend");
const BACKEND_DATA_DIR = path.join(BACKEND_DIR, "data");
const README_PATH = path.join(__dirname, "..", "..", "README.md");
const LOGS_DIR = path.join(__dirname, "..", "..", "logs");
const BACKEND_HOST = "127.0.0.1";
const BACKEND_PORT = 8765;

// Optional — falls back to Electron's default icon if wordscroll.ico hasn't
// been generated yet (see README's "Icon" note / install.ps1).
const _iconCandidate = path.join(__dirname, "..", "..", "wordscroll.ico");
const WORDSCROLL_ICON = fs.existsSync(_iconCandidate) ? _iconCandidate : undefined;

const GITHUB_REPO = "UdoEmmanuel/wordscroll";

let mainWindow = null;
let backendProcess = null;

// The Desktop shortcut launches electron.exe directly (see install.ps1) —
// deliberately no PowerShell/console wrapper in between, since a flashing
// terminal window before the app appears reads as broken/scary to an
// operator who isn't technical. That means nothing prints to a visible
// console any more, so this is the only remaining way to see what
// happened if something goes wrong: every console.log/error (this file's
// own, plus every "[backend] ..." line from the spawned Python process)
// also gets written to a timestamped file here.
fs.mkdirSync(LOGS_DIR, { recursive: true });
const logStream = fs.createWriteStream(
  path.join(LOGS_DIR, `wordscroll-${new Date().toISOString().replace(/[:.]/g, "-")}.log`),
  { flags: "a" }
);
for (const method of ["log", "error", "warn"]) {
  const original = console[method].bind(console);
  console[method] = (...args) => {
    original(...args);
    logStream.write(`${args.map(String).join(" ")}\n`);
  };
}

// True if something is already answering on BACKEND_HOST:BACKEND_PORT —
// either a backend this same launch already started, or one the operator
// started by hand (e.g. mid-development, following the README's old manual
// steps). Spawning a second one would just fail to bind the port and exit
// immediately, so this is checked before ever spawning.
function isBackendUp() {
  return new Promise((resolve) => {
    const req = http.get({ host: BACKEND_HOST, port: BACKEND_PORT, path: "/theme", timeout: 1000 }, (res) => {
      res.resume(); // drain so the socket can close cleanly
      resolve(true);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

// Spawns the backend in the background and returns immediately — does NOT
// wait for it to finish starting up. That's deliberate: the renderer's own
// device list, model-ready, and WebSocket connections all already retry on
// a short interval (see renderer.js) precisely so the UI can come up first
// and self-heal once the backend catches up a few seconds later, rather
// than the window staying blank while Whisper's model loads.
async function startBackend() {
  if (await isBackendUp()) {
    console.log(`[backend] already running on ${BACKEND_HOST}:${BACKEND_PORT} — not starting another`);
    return;
  }

  const pythonExe = path.join(BACKEND_DIR, "venv", "Scripts", "python.exe");
  if (!fs.existsSync(pythonExe)) {
    console.error(
      `[backend] no venv found at ${pythonExe} — see README Setup. The app will still open, but nothing will work until the backend is available.`
    );
    return;
  }

  backendProcess = spawn(
    pythonExe,
    ["-m", "uvicorn", "main:app", "--host", BACKEND_HOST, "--port", String(BACKEND_PORT)],
    { cwd: BACKEND_DIR }
  );
  backendProcess.stdout.on("data", (chunk) => console.log(`[backend] ${chunk.toString().trimEnd()}`));
  backendProcess.stderr.on("data", (chunk) => console.error(`[backend] ${chunk.toString().trimEnd()}`));
  backendProcess.on("exit", (code, signal) => {
    console.log(`[backend] process exited (code=${code}, signal=${signal})`);
    backendProcess = null;
  });
  backendProcess.on("error", (err) => {
    console.error("[backend] failed to start:", err);
    backendProcess = null;
  });
}

// Only kills a backend THIS launch started — one already running before the
// app opened (isBackendUp() found it) is left alone, since it isn't ours to
// stop and something else may depend on it (e.g. it was started manually).
function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

// Compares two "vX.Y.Z" (or "X.Y.Z") tags numerically, part by part —
// simple on purpose, no semver package needed for the plain-integer
// version scheme this project actually uses.
function isNewerVersion(latest, current) {
  const clean = (v) => v.replace(/^v/i, "").split(".").map((n) => parseInt(n, 10) || 0);
  const a = clean(latest);
  const b = clean(current);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const diff = (a[i] || 0) - (b[i] || 0);
    if (diff !== 0) return diff > 0;
  }
  return false;
}

// Check-and-notify only — deliberately not a silent self-updater. A silent
// updater that downloads and replaces its own running files is exactly the
// pattern that got the compiled-.exe approach blocked by Windows
// Application Control in the first place (see README's Packaging section);
// this just tells the operator a newer version exists and hands them the
// release page, same trust model as everything else in this app.
function checkForUpdates() {
  const req = https.get(
    {
      hostname: "api.github.com",
      path: `/repos/${GITHUB_REPO}/releases/latest`,
      headers: { "User-Agent": "wordscroll-app" },
      timeout: 5000,
    },
    (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        if (res.statusCode !== 200) return; // no releases yet, rate-limited, offline, etc. — silently skip, never nag on failure
        try {
          const release = JSON.parse(body);
          if (isNewerVersion(release.tag_name, packageJson.version) && mainWindow) {
            mainWindow.webContents.send("update-available", {
              version: release.tag_name,
              url: release.html_url,
            });
          }
        } catch {
          // malformed response — skip silently, same as any other failure here
        }
      });
    }
  );
  req.on("error", () => {}); // offline/DNS failure — this must never interrupt a live service, so fail silently
  req.on("timeout", () => req.destroy());
}

ipcMain.on("open-update-page", (_event, url) => {
  if (url && url.startsWith("https://github.com/")) shell.openExternal(url);
});

function send(action) {
  if (mainWindow) mainWindow.webContents.send("menu-action", action);
}

function buildMenu() {
  const isMac = process.platform === "darwin";

  const template = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" },
              { type: "separator" },
              { role: "services" },
              { type: "separator" },
              { role: "hide" },
              { role: "hideOthers" },
              { role: "unhide" },
              { type: "separator" },
              { role: "quit" },
            ],
          },
        ]
      : []),
    {
      label: "File",
      submenu: [
        {
          label: "Open Data Folder",
          click: () => shell.openPath(BACKEND_DATA_DIR),
        },
        {
          label: "Reload Overlay Cache",
          accelerator: "CmdOrCtrl+Shift+R",
          click: async () => {
            await session.defaultSession.clearCache();
            send("reload-overlays");
          },
        },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit" },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "Capture",
      submenu: [
        {
          label: "Start",
          accelerator: "CmdOrCtrl+Shift+S",
          click: () => send("start-capture"),
        },
        {
          label: "Stop",
          accelerator: "CmdOrCtrl+Shift+X",
          click: () => send("stop-capture"),
        },
        { type: "separator" },
        {
          label: "Focus Reference Search",
          accelerator: "F5",
          registerAccelerator: false, // let the page's own F5 handler (hotkeys.js) fire; this just documents it in the menu
          click: () => send("focus-reference"),
        },
        {
          label: "Focus Keyword Search",
          accelerator: "F6",
          registerAccelerator: false,
          click: () => send("focus-keyword"),
        },
      ],
    },
    {
      label: "Display",
      submenu: [
        {
          label: "Advance Queue",
          accelerator: "CmdOrCtrl+Shift+N",
          click: () => send("advance-queue"),
        },
        {
          label: "Favorite Current",
          accelerator: "CmdOrCtrl+Shift+F",
          click: () => send("favorite-current"),
        },
        {
          label: "Add Current to Queue",
          accelerator: "CmdOrCtrl+Shift+Q",
          click: () => send("queue-current"),
        },
        {
          label: "Clear Display",
          accelerator: "CmdOrCtrl+Shift+C",
          click: () => send("clear-display"),
        },
        { type: "separator" },
        {
          label: "Clear History",
          click: () => send("clear-history"),
        },
        { type: "separator" },
        {
          label: "Open Theme Settings...",
          accelerator: "CmdOrCtrl+T",
          click: () => send("open-theme"),
        },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "forceReload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Window",
      submenu: [
        { role: "minimize" },
        { role: "zoom" },
        ...(isMac ? [{ type: "separator" }, { role: "front" }] : [{ role: "close" }]),
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "View README",
          click: () => shell.openPath(README_PATH),
        },
        {
          label: "Reference Short Codes",
          click: () => shell.openExternal("http://127.0.0.1:8765/reference/short-codes.html"),
        },
        { type: "separator" },
        {
          label: `About ${app.name}`,
          click: () =>
            dialog.showMessageBox(mainWindow, {
              type: "info",
              title: `About ${app.name}`,
              message: "AI Bible Transcriber",
              detail: `Version ${packageJson.version}\n${packageJson.description}`,
              buttons: ["OK"],
            }),
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1000,
    height: 700,
    show: false, // avoid a visible resize-then-maximize flash on launch
    backgroundColor: "#111318",
    icon: WORDSCROLL_ICON, // title bar + taskbar — otherwise shows Electron's generic icon even though the Desktop shortcut is branded (install.ps1 sets that separately, since a .lnk's icon isn't read from here)
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  mainWindow = win;
  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });
  // Renderer-side errors (a bad element ID, an uncaught exception in
  // renderer.js/theme.js/etc.) land in DevTools' console, not this
  // process's own console — invisible in logs/ otherwise, and there's no
  // visible console at all once launched from the Desktop shortcut.
  const CONSOLE_LEVELS = ["log", "log", "warn", "error"]; // Electron's 0=verbose..3=error; only log/warn/error are wrapped to also write to logs/ (see the top of this file)
  win.webContents.on("console-message", (event) => {
    const level = CONSOLE_LEVELS[event.level] || "log";
    console[level](`[renderer:${event.sourceId?.split("/").pop() ?? "?"}:${event.lineNumber}]`, event.message);
  });

  win.once("ready-to-show", () => {
    win.maximize(); // fills the screen but keeps window chrome (title bar, taskbar) — not exclusive fullscreen
    win.show();
  });

  // Waits for the renderer's own JS (which registers the "update-available"
  // listener) to have actually run before checking — checking any earlier
  // risks the IPC message arriving before anything is listening for it and
  // getting silently dropped.
  win.webContents.once("did-finish-load", checkForUpdates);

  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(async () => {
  // The overlay iframes (Now Displaying, Theme preview) load overlay.css/js
  // from the backend over plain HTTP — Electron's disk cache persists
  // across app restarts just like a real browser profile, so a stale
  // cached copy from an earlier version of those files (before a fix
  // shipped) can silently keep serving forever even with proper no-cache
  // response headers, since those headers only prevent *future* staleness,
  // not an entry already cached before they existed. Clearing cache on
  // every launch makes this a non-issue permanently.
  await session.defaultSession.clearCache();
  startBackend(); // fire-and-forget — see startBackend()'s comment for why this isn't awaited
  buildMenu();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("will-quit", () => {
  stopBackend();
});
