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
- Optional (`VERSION_SUFFIX=on`): a file ending `_U01` replaces the story's clip, a file ending `_V01` is added next to it; no +Version click (see `docs/CHANGES_v1050.md`)
- A story with several clips (the plain clip plus `_V01` / `_U01` files) shows them together as one **Story Media Gallery** card in the Media & IDs pane, each with its own Play preview (see `docs/CHANGES_v1060.md`)
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

## Release history

Release highlights, newest first. Each version links to its full notes.

- [v10.9.8](docs/CHANGES_v1098.md) - The selected-text count floats above the selection instead of sitting in the footer.

- [v10.9.7](docs/CHANGES_v1097.md) - Script pane: every Online / Anchor text in its own box, word count and reading time (words per minute), count for the selected text.

- [v10.9.6](docs/CHANGES_v1096.md) - Editor filter in the Ready feed; Electron desktop app (`electron/INSTRUCTIONS.md`).
- [v10.9.5](docs/CHANGES_v1095.md) - Editor name (Blaze slug comment) filter and search, header tabs, and the editor shown in the Ready feed's Assigned to column.
- [v10.6.1](docs/CHANGES_v1061.md) - Quick test recognizes clips the desk already attached, reports why a clip cannot be marked, and explains verification requirements for story format 22.
- [v10.6.0](docs/CHANGES_v1060.md) - Multi-clip stories appear together in a Story Media Gallery with per-clip details and previews.
- [v10.5.0](docs/CHANGES_v1050.md) - Optional filename suffixes add clips (`_Vnn`) or replace the main clip (`_Unn`) without using +Version.
- [v10.4.0](docs/CHANGES_v1040.md) - Shared stories are attached once and all matching clip IDs are marked attached; read-back handling and row ordering are fixed.
- [v10.3.0](docs/CHANGES_v1030.md) - Ready feed becomes a searchable table with story navigation and Quick test attach.
- [v10.2.0](docs/CHANGES_v1020.md) - Adds a searchable Ready feed, in-page notifications, and optional chat webhook notifications.
- [v10.1.1](docs/CHANGES_v1011.md) - Refresh updates only changed page content and can be paused.
- [v10.1.0](docs/CHANGES_v1010.md) - Streams low-resolution previews from Nitro without storing them.
- [v10.0.0](docs/CHANGES_v1000.md) - Introduces the three-pane workspace for stories, scripts, and media.
- [Three-pane layout](docs/CHANGES_3pane_layout.md) - Documents the pane proportions and a standalone sample dashboard.
- [v9.16.1](docs/CHANGES_v9161.md) - Keeps bulletin times in a narrow left column on phones.
- [v9.16.0](docs/CHANGES_v9160.md) - Adds separate bulletin and story panes with a story-details popup.
- [v9.15.0](docs/CHANGES_v9150.md) - Places bulletin times, selected-bulletin stories, and details in three distinct areas.
- [v9.14.0](docs/CHANGES_v9140.md) - Adds compact story rows and a details panel with Previous/Next navigation.
- [v9.13.6](docs/CHANGES_v9136.md) - Keeps Quick test visible and explains when it cannot run.
- [v9.13.5](docs/CHANGES_v9135.md) - Adds a poller command to inspect a story's script fields.
- [v9.13.4](docs/CHANGES_v9134.md) - Fixes an empty dashboard caused by missing database columns after an upgrade.
- [v9.13.2](docs/CHANGES_v9132.md) - Displays Blaze's online and anchor script fields on story cards and in details.
- [v9.13.1](docs/CHANGES_v9131.md) - Explains attachment status, warns about unapplied configuration edits, and prevents multiple pollers.
- [v9.13 restructured build](docs/CHANGES_v913_restructure.md) - Restructures the build and database schema without changing behavior, and fixes self-test.
- [v9.13](docs/CHANGES_v913.md) - Adds Quick test attach to stories with safeguards for readiness and verified formats.
- [v9.12](docs/CHANGES_v912.md) - Allows running without Playout/Nitro folder mounts by disabling the watcher.
- [v9.11](docs/CHANGES_v911.md) - Improves shared-story attachment read-back, status logging, date parsing, and media-based confirmation.
- [v9.8.1](docs/CHANGES_v981.md) - Final Storigen-branded release in the v9.8 series.
- [v9.8.0](docs/CHANGES_v980.md) - Final release under the earlier product name.
- [v9.7.5](docs/CHANGES_v975.md) - Adds the four-step clip status strip and the earlier product branding, with review fixes.
- [v9.7.4](docs/CHANGES_v974.md) - Uses one media list per polling round, distinguishes converting files from ready files, and adds a sign-in page.
- [v9.7.3](docs/CHANGES_v973.md) - Adds automatic Blaze login and session renewal.
- [v9.7.2](docs/CHANGES_v972.md) - Uses date-and-story clip names shared by repeated stories; includes v9.7.1.
- [v9.7.1](docs/CHANGES_v971.md) - Introduces date-and-story clip names shared by repeated stories.
- [v9.6.0](docs/CHANGES_v95.md) - Merges polling improvements, bounded parallel reads, retry and day controls, dashboard improvements, and new-version handling.
- [v9.4](docs/CHANGES_v94.md) - Introduces complete-day polling and a paged dashboard.
- [v9.4 plain ZIP](docs/CHANGES_v94_plain_zip.md) - Documents the plain ZIP build's complete-day polling dashboard.
- [v9.3](docs/CHANGES_v93.md) - Discovers shows automatically and uses captured Blaze data.
- [v9.2](docs/CHANGES_v92.md) - Adds the dashboard and reporting page.
- [v9.1](docs/CHANGES_v91.md) - Improves long-running polling, reconciliation, session reload, alerts, and Windows watcher behavior.

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
