// Only the local setup page (file:) gets the two settings calls; the dashboard page from the server gets nothing.
const { contextBridge, ipcRenderer } = require("electron");
if (location.protocol === "file:") {
  contextBridge.exposeInMainWorld("storigen", {
    getServer: () => ipcRenderer.invoke("get-server"),
    setServer: v => ipcRenderer.invoke("set-server", v)
  });
}
