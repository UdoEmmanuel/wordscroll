// Light/dark theme for the operator app's own UI (renderer/styles.css) —
// unrelated to the on-screen verse Theme (theme.js / theme_store.py), which
// styles the OBS/NDI output instead. Persisted in localStorage so it
// survives restarts; defaults to dark to match the app's original look for
// anyone with no saved preference yet.
const UI_THEME_KEY = "ui-theme";
const uiThemeToggleBtn = document.getElementById("ui-theme-toggle-btn");
const uiThemeToggleIcon = document.getElementById("ui-theme-toggle-icon");

function applyUiTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const isLight = theme === "light";
  // Icon shows the theme a click switches TO: moon while light (click for dark), sun while dark (click for light).
  uiThemeToggleIcon.textContent = isLight ? "☾" : "☀";
  const nextLabel = isLight ? "Switch to dark theme" : "Switch to light theme";
  uiThemeToggleBtn.title = nextLabel;
  uiThemeToggleBtn.setAttribute("aria-label", nextLabel);
}

function loadUiTheme() {
  try {
    return localStorage.getItem(UI_THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark"; // storage unavailable — fall back to the original default
  }
}

let currentUiTheme = loadUiTheme();
applyUiTheme(currentUiTheme);

uiThemeToggleBtn.addEventListener("click", () => {
  currentUiTheme = currentUiTheme === "light" ? "dark" : "light";
  applyUiTheme(currentUiTheme);
  try {
    localStorage.setItem(UI_THEME_KEY, currentUiTheme);
  } catch {
    // storage unavailable — theme still applies for this session, just won't persist
  }
});
