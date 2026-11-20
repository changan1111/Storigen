# Storigen desktop app (Electron) - how to make it

The app is a window that shows the Storigen dashboard. **The Storigen server (`autoid.py`) keeps running on the Mac mini exactly as before**; the app only opens its page (the same page you open in the browser). Install the app on any Mac or Windows PC that can reach the server.

Build the Mac app on a Mac, and the Windows app on a Windows PC.

## 1. One-time: install Node.js
Download the **LTS** version from https://nodejs.org and install it. Check in Terminal (Mac) or PowerShell (Windows):

    node -v
    npm -v

## 2. Build
Open Terminal / PowerShell in this project, then:

    cd electron
    npm install

Try it first (opens the window, nothing is installed):

    npm start

On the first start it asks for the **server address**, for example `http://janamedit01.local:8081` (the Mac mini name and the `WEB_PORT` from `autoid.env`). Type it and press Connect. Tick nothing else; it is remembered.

Make the installer:

    npm run dist:mac        # on a Mac     -> electron/dist/Storigen-10.9.8.dmg (or -arm64.dmg)
    npm run dist:win        # on Windows   -> electron/dist/Storigen Setup 10.9.8.exe

(The first build downloads Electron, so it needs internet and takes a few minutes.)

## 3. Install
* **Mac:** open the `.dmg`, drag **Storigen** to Applications. The first time, right-click the app and choose **Open**, then Open again (the app is not signed). If macOS still blocks it: System Settings > Privacy & Security > **Open Anyway**.
* **Windows:** run the Setup `.exe`. If SmartScreen warns, click **More info > Run anyway**.

## 4. Use
* The window is the normal dashboard: Rundown, Ready feed (with its Users and Editors filters), Recent activity, Users.
* **Change the server address:** menu **Storigen > Change server address...** If the server cannot be reached, the app shows the address page with the reason; fix the address or start the server, then Connect again.
* **Storigen > Open in the browser** opens the same address in your normal browser.
* Reload: Ctrl/Cmd+R. Zoom: View menu. CSV export asks where to save the file.

## 5. Optional
* **Start with the computer.** Mac: System Settings > General > Login Items > add Storigen. Windows: press Win+R, type `shell:startup`, put a shortcut to Storigen in that folder.
* **Own icon.** Put `icon.icns` (Mac) and `icon.ico` (Windows) in `electron/build/` before `npm run dist:...`.
* **Forget the saved address by hand.** Delete `config.json` in the app's data folder: Mac `~/Library/Application Support/Storigen/`, Windows `%APPDATA%\Storigen\` (when started with `npm start` the folder is called `storigen-desktop`).
* **Update the app after a new Storigen version.** The page comes from the server, so updating the server updates what the app shows; rebuild the app only if you change the files inside `electron/`.

## Files
* `main.js` - window, menu, remembered server address, error handling
* `preload.js`, `setup.html`, `setup.js` - the address page (the dashboard page gets no access to the app)
* `package.json` - build settings (electron-builder)
