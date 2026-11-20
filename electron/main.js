// Storigen desktop window (Electron). It only SHOWS the dashboard that the Storigen server already serves;
// the server (autoid.py) keeps running on the Mac mini as before. The server address is asked once and remembered.
const { app, BrowserWindow, Menu, ipcMain, shell } = require("electron");
const path = require("path");
const fs = require("fs");

const DEFAULT_SERVER = "http://localhost:8080";   // WEB_PORT in autoid.env; change it in the app: Storigen > Change server address
let win = null;

const cfgFile = () => path.join(app.getPath("userData"), "config.json");
function readCfg() { try { return JSON.parse(fs.readFileSync(cfgFile(), "utf8")) || {}; } catch (e) { return {}; } }
function writeCfg(c) { fs.mkdirSync(app.getPath("userData"), { recursive: true }); fs.writeFileSync(cfgFile(), JSON.stringify(c, null, 2)); }
function normalize(v) {
  v = String(v || "").trim();
  if (!v) return "";
  if (!/^https?:\/\//i.test(v)) v = "http://" + v;
  try { return new URL(v).origin; } catch (e) { return ""; }
}
const fromSetupPage = e => { try { return String(e.senderFrame.url).startsWith("file:"); } catch (x) { return false; } };

function showSetup(error) {
  if (!win) return;
  const query = { server: readCfg().server || DEFAULT_SERVER };
  if (error) query.error = error;
  win.loadFile(path.join(__dirname, "setup.html"), { query });
}
function loadServer() {
  const s = readCfg().server;
  if (!s) return showSetup();
  win.loadURL(s).catch(() => {});   // a failure is handled in did-fail-load
}

function createWindow() {
  win = new BrowserWindow({
    width: 1500, height: 950, minWidth: 900, minHeight: 600, title: "Storigen", backgroundColor: "#ffffff",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  win.webContents.on("did-fail-load", (_e, code, desc, url, isMainFrame) => {
    if (!isMainFrame || code === -3 || String(url).startsWith("file:")) return;   // -3 = a load that was replaced by another one
    showSetup("Cannot reach " + url + " (" + desc + "). Check that the Storigen server is running and the address is right.");
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    const s = readCfg().server;
    let same = false; try { same = !!s && new URL(url).origin === new URL(s).origin; } catch (e) {}
    if (same) return { action: "allow" };   // /report and other pages of the same server open in a window of their own
    shell.openExternal(url); return { action: "deny" };
  });
  win.webContents.on("page-title-updated", e => e.preventDefault());   // keep the title "Storigen"
  win.on("closed", () => { win = null; });
  loadServer();
}

ipcMain.handle("get-server", e => (fromSetupPage(e) ? (readCfg().server || DEFAULT_SERVER) : ""));
ipcMain.handle("set-server", (e, v) => {
  if (!fromSetupPage(e)) return { ok: false, error: "not allowed" };
  const n = normalize(v);
  if (!n) return { ok: false, error: "That is not a valid address. Example: http://janamedit01.local:8081" };
  writeCfg(Object.assign(readCfg(), { server: n }));
  loadServer();
  return { ok: true };
});

function buildMenu() {
  const mac = process.platform === "darwin";
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(mac ? [{ role: "appMenu" }] : []),
    { label: "Storigen", submenu: [
      { label: "Change server address…", click: () => showSetup() },
      { label: "Open in the browser", click: () => { const s = readCfg().server; if (s) shell.openExternal(s); } },
      { type: "separator" }, { role: "reload" }, { role: "forceReload" },
      ...(mac ? [] : [{ type: "separator" }, { role: "quit" }])
    ] },
    { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" }
  ]));
}

if (!app.requestSingleInstanceLock()) { app.quit(); }
else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(() => {
    buildMenu(); createWindow();
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
  });
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
}
