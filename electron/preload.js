/**
 * electron/preload.js
 *
 * Runs in the renderer process (your frontend) but has access to
 * Node.js APIs. We use it as a controlled bridge — exposing only
 * what the frontend actually needs, nothing more.
 *
 * contextIsolation: true  (set in main.js) means the renderer can't
 * access Node directly — it can only use what we expose here via
 * contextBridge. This is the secure Electron pattern.
 *
 * Right now we expose one thing: a flag telling the frontend it's
 * running inside Electron (vs a normal browser). The frontend can
 * use this to show/hide Electron-specific UI like the tray hint.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lockbox', {
  // Let the frontend know it's running in Electron
  isElectron: true,

  // Lock vault and minimise to tray
  lockAndHide: () => ipcRenderer.send('lock-and-hide'),

  // Quit the app entirely
  quit: () => ipcRenderer.send('quit-app'),
});