/**
 * electron/main.js
 *
 * LockBox Electron entry point.
 *
 * Responsibilities:
 *   1. Spawn the Python/uvicorn backend as a child process
 *   2. Wait until the backend is actually ready (port check)
 *   3. Open the main window pointing at localhost:8000
 *   4. Show a system tray icon with open/lock/quit options
 *   5. Kill the backend cleanly when the app exits
 *
 * Why spawn instead of bundle a compiled binary?
 *   You already have the venv and backend working. Spawning uvicorn
 *   directly reuses everything you've built with zero changes to the
 *   Python code. When we move to Phase B we can compile to a binary,
 *   but for now this is simpler and easier to debug.
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, dialog } = require('electron');
const { spawn } = require('child_process');
const path  = require('path');
const net   = require('net');
const fs    = require('fs');

// ── Config ─────────────────────────────────────────────────────────────────
const PORT        = 8000;
const HOST        = '127.0.0.1';
const READY_TIMEOUT_MS  = 15000;  // how long to wait for backend to start
const READY_POLL_MS     = 200;    // how often to check if port is open

// ── Resolve paths ──────────────────────────────────────────────────────────
// app.getAppPath() works both in dev (project root) and in packaged app.
const APP_ROOT    = app.isPackaged
  ? path.join(process.resourcesPath)
  : path.join(__dirname, '..');

const UVICORN     = path.join(APP_ROOT, 'venv', 'bin', 'uvicorn');
const PYTHON      = path.join(APP_ROOT, 'venv', 'bin', 'python3');

// ── State ──────────────────────────────────────────────────────────────────
let backendProcess = null;
let mainWindow     = null;
let tray           = null;
let isQuitting     = false;   // flag so window close → tray, not quit

// ── Backend management ─────────────────────────────────────────────────────

/**
 * Start the uvicorn backend and return a Promise that resolves
 * when the port is accepting connections, or rejects on timeout.
 */
function startBackend() {
  return new Promise((resolve, reject) => {
    console.log('[LockBox] Starting backend...');
    console.log('[LockBox] uvicorn path:', UVICORN);
    console.log('[LockBox] app root:', APP_ROOT);

    backendProcess = spawn(UVICORN, [
      'backend.main:app',
      '--host', HOST,
      '--port', String(PORT),
      '--log-level', 'warning',   // less noise in production
    ], {
      cwd: APP_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: APP_ROOT,     // so 'import backend' works
      },
    });

    backendProcess.stdout.on('data', d => console.log('[backend]', d.toString().trim()));
    backendProcess.stderr.on('data', d => console.log('[backend]', d.toString().trim()));

    backendProcess.on('error', err => {
      console.error('[LockBox] Failed to start backend:', err);
      reject(err);
    });

    backendProcess.on('exit', (code, signal) => {
      console.log(`[LockBox] Backend exited — code=${code} signal=${signal}`);
      // If it exits unexpectedly while app is running, show an error
      if (!isQuitting && mainWindow) {
        dialog.showErrorBox(
          'LockBox backend stopped',
          'The backend process exited unexpectedly. Please restart LockBox.'
        );
      }
    });

    // Poll until port is open
    waitForPort(PORT, HOST, READY_TIMEOUT_MS, READY_POLL_MS)
      .then(resolve)
      .catch(reject);
  });
}

/**
 * Poll HOST:PORT every intervalMs until it accepts a TCP connection
 * or timeoutMs is exceeded.
 */
function waitForPort(port, host, timeoutMs, intervalMs) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    function attempt() {
      const sock = new net.Socket();
      sock.setTimeout(intervalMs);

      sock.connect(port, host, () => {
        sock.destroy();
        resolve();
      });

      sock.on('error', () => {
        sock.destroy();
        if (Date.now() >= deadline) {
          reject(new Error(`Backend did not start within ${timeoutMs}ms`));
        } else {
          setTimeout(attempt, intervalMs);
        }
      });

      sock.on('timeout', () => {
        sock.destroy();
        if (Date.now() >= deadline) {
          reject(new Error(`Backend did not start within ${timeoutMs}ms`));
        } else {
          setTimeout(attempt, intervalMs);
        }
      });
    }

    attempt();
  });
}

function stopBackend() {
  if (backendProcess) {
    console.log('[LockBox] Stopping backend...');
    backendProcess.kill('SIGTERM');
    backendProcess = null;
  }
}

// ── Window ─────────────────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1100,
    height: 720,
    minWidth:  800,
    minHeight: 500,
    title: 'LockBox',
    backgroundColor: '#0f1117',   // match --bg-base so no white flash on load
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,     // security: no Node in renderer
    },
    icon: path.join(APP_ROOT, 'assets', 'icon.png'),
    show: false,                  // don't show until ready-to-show fires
  });

  mainWindow.loadURL(`http://${HOST}:${PORT}`);

  // Show window once the page has loaded — avoids white flash
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Clicking X minimises to tray instead of quitting
  mainWindow.on('close', e => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
      tray.displayBalloon?.({        // Windows only, no-op on Linux
        title: 'LockBox',
        content: 'LockBox is still running in the tray.',
      });
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Tray ────────────────────────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(APP_ROOT, 'assets', 'icon.png');
  const icon     = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  tray           = new Tray(icon);

  tray.setToolTip('LockBox');
  tray.setContextMenu(buildTrayMenu());

  // Left-click on tray icon shows/hides the window
  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
    }
  });
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    {
      label: 'Open LockBox',
      click: () => { if (mainWindow) mainWindow.show(); },
    },
    {
      label: 'Lock vault',
      click: async () => {
        // Call the lock endpoint, then show the window so user can unlock
        try {
          await fetch(`http://${HOST}:${PORT}/api/lock`, { method: 'POST' });
        } catch (_) {}
        if (mainWindow) mainWindow.show();
      },
    },
    { type: 'separator' },
    {
      label: 'Quit LockBox',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
}

// ── App lifecycle ───────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Show a loading splash in the dock/taskbar while backend starts
  Menu.setApplicationMenu(null);
  app.setName('LockBox');

  try {
    await startBackend();
    console.log('[LockBox] Backend ready');
  } catch (err) {
    dialog.showErrorBox(
      'LockBox failed to start',
      `Could not start the backend server:\n\n${err.message}\n\nMake sure the venv exists at:\n${UVICORN}`
    );
    app.quit();
    return;
  }

  createWindow();
  createTray();
});

// Clean up backend when Electron quits
app.on('before-quit', () => {
  isQuitting = true;
  stopBackend();
});

// On macOS, clicking the dock icon re-opens the window
app.on('activate', () => {
  if (mainWindow) mainWindow.show();
});

// Prevent app from quitting when all windows are closed (we use tray)
app.on('window-all-closed', () => {
  // Do nothing — tray keeps the app alive
  // User must use Tray → Quit to fully exit
});