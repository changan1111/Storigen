# Auto-ID Linker Lite

Auto-ID Linker Lite is a lightweight Python service that watches media folders, links finished clips to Blaze stories, tracks daily status, and can optionally attach the clip back to Blaze when enabled.

It is designed for broadcast operations teams that need a simple, local workflow without Docker or third-party dependencies. The app exposes a browser dashboard, daily reporting, and status checks for the watcher, Blaze poller, and local service.

## What it does

- Watches Playout INBOX and Nitro ONAIR folders for incoming media files
- Assigns clip IDs to stories and tracks status through the workflow
- Matches finished clips to the correct Blaze story
- Supports both `placeholder` and `story_id` linking modes
- Offers a dashboard and reporting pages for operations staff
- Can optionally attach clips to Blaze stories in live mode
- Includes a Blaze DataService poller and optional MOS gateway support
- Keeps the process running with restart supervision and health checks

## Supported workflow

The tool is intended for a read-only first pass and can be made live only when the operator confirms they want the attachment step enabled.

Key operational rules from the project docs:

- Use a dedicated Blaze user account for the tool
- Treat the session cookie or login credentials as sensitive secrets
- Keep the folder access read-only for Nitro/Playout unless the workflow explicitly requires live writes
- Validate settings with the built-in `doctor` and `selftest` checks before going live

## Repository layout

- `autoid.py` — CLI entry point for init, doctor, run, selftest, status, and backup
- `autoid.env.example` — sample environment configuration with all major settings
- `autoid_lite/` — core application code, watcher, dashboard, and Blaze integration
- `deploy/` — OS-specific install helpers for macOS and Windows
- `docs/` — installation guides, changelogs, architecture notes, and PDF documentation
- `tests/` — automated project tests
- `tools/` — helper scripts and operational utilities

## Quick start

### 1) Create the configuration file

From the project root:

```bash
python3 autoid.py init
```

This creates `autoid.env` with generated secrets and admin credentials.

### 2) Review the editable settings

Open `autoid.env` and set the folder paths and local environment details for your station.

Typical values include:

- `WATCH_MODE`
- `EXPORTS_DIR`
- `INBOX_SUBDIRS`
- `NITRO_DIR`
- `WEB_HOST`
- `WEB_PORT`
- `BLAZE_POLL`
- `BLAZE_URL`
- `BLAZE_SHOW_IDS`
- `LINK_MODE`

### 3) Validate the setup

```bash
python3 autoid.py doctor
```

This checks the Python version, SQLite availability, and required settings before the service starts.

### 4) Start the service

```bash
python3 autoid.py run
```

Then open the app in a browser:

```text
http://<hostname>:8080
```

Use the generated admin email/password from the `init` step, then update settings as needed.

## Installation notes

### macOS

Use the provided deployment script:

```bash
./deploy/mac/install_mac.sh you@company.com
```

The script creates `autoid.env`, seeds the app secrets, and configures a launchd job. Follow the installation guide in `docs/INSTALL.html` or the PDF in `docs/Storigen_Install_and_Operations_Guide.pdf` for the full operational steps, including mounting NAS shares and enabling launchd startup.

### Windows

Use the Windows installer script from PowerShell as Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install_windows.ps1
```

Then update the UNC paths in `autoid.env` and validate with `python autoid.py doctor`.

## Configuration highlights

The sample file `autoid.env.example` contains the main operational options. The most important ones are:

- `LINK_MODE=placeholder` or `story_id`
- `BROADCAST_DAY_START=05:00`
- `WATCH_MODE=observe`
- `EXPORTS_DIR=/Volumes/Playout/INBOX`
- `NITRO_DIR=/Volumes/Nitro/ONAIR`
- `BLAZE_POLL=0` or `1`
- `BLAZE_SHOW_IDS=auto`
- `BLAZE_ATTACH=dry` until live attachment is verified
- `BLAZE_CONFIRM=1`

For live attachment, the project documentation recommends testing with a limited scope first and making sure the attach action is only enabled after verifying the configuration.

## Operational commands

```bash
python3 autoid.py init
python3 autoid.py doctor
python3 autoid.py run
python3 autoid.py status
python3 autoid.py selftest
python3 autoid.py backup
```

### Command behavior

- `init` creates a secure default env file if it does not exist
- `doctor` checks local health and configuration
- `run` starts the app and supervision processes
- `status` checks whether the running service is healthy
- `selftest` runs a short end-to-end validation on a free local port
- `backup` creates a backup of the SQLite database

## Documentation

For installation and operational guidance, refer to:

- `docs/INSTALL.html`
- `docs/Storigen_Install_and_Operations_Guide.pdf`
- `docs/ARCHITECTURE.md`
- `docs/CHANGELOG.md` and the version-specific changelogs in `docs/`

## Security and access considerations

- Do not share the Blaze session cookie or secret values in chat, screenshots, or source control
- Use a dedicated account with the minimum required permissions
- Keep the tool in `dry` or `observe` mode until the workflow is validated
- Do not run the service with broad write access to shared storage unless required

## License and support

This project is distributed as part of the local station tooling set and is intended for internal broadcast operations use. Refer to the project documentation and operational procedures for your environment before putting the tool into live production mode.

## Quick summary

If you want the shortest path to evaluation:

```bash
python3 autoid.py init
python3 autoid.py doctor
python3 autoid.py run
```

Then confirm the dashboard is reachable and the folder/watcher checks are clean before enabling live Blaze attachment.
