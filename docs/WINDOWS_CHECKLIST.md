# Windows: what to verify on the real machine (v9.1)

The Windows install script was never run on a real PC, and the tests here run on Mac/Linux. v9.1 fixes the Windows problems found by reading the code and tests them with a faked Windows API (`tests/test_windows_safety.py`). That is not the same as a real run. Do this once and send me every FIX line or failure.

1. **Python 3.9+** from python.org ("Add python.exe to PATH"). `python --version`.
2. **Folder** such as `C:\AutoID` and a **dedicated Windows user** that can read the Playout and Nitro shares (Nitro read-only).
3. **UNC paths only** in `autoid.env` (`\\nas\Playout\INBOX`, `\\nas\Nitro\ONAIR`). A service cannot see mapped drive letters.
4. `python autoid.py init you@company.com` (the first password is printed once).
5. Edit `autoid.env`, then `python autoid.py doctor` (fix every FIX line) and `python autoid.py selftest`.
6. PowerShell as Administrator: `powershell -ExecutionPolicy Bypass -File deploy\windows\install_windows.ps1 -User DOMAIN\autoid -Password '...'`. It now also limits `autoid.env` to that user + Administrators and turns off sleep.
7. `Start-ScheduledTask AutoID`, then open `http://<this-pc>:8080` from **another** PC. The script opens port 8080 for every network profile: restrict it to Domain/Private if the PC is on other networks.
8. **Reboot test:** restart the PC, do not log in, check the page is up and all components are green. Stop and start the task once.
9. **Cookie refresher:** if Playwright writes `autoid.env` under a different Windows user, give that user Modify rights on the file. The poller picks the new cookie up within a poll, no restart.
10. **Tests** (optional): `python -m pip install pytest`, then `python -m pytest tests -q`. Some tests were written on Mac/Linux: tell me which fail and I will fix them.

## Differences from the Mac
- **No nightly 04:30 restart on Windows yet.** The Mac has one. I did not add it because I cannot confirm that stopping the task also stops the three child processes (a leftover would hold port 8080). Decide after step 8.
- Keep `WATCH_MODE=observe` (the default). Copy mode relies on hard links and lock files that are untested on SMB from Windows.
- `os.kill(pid, 0)` terminates a process on Windows: replaced in the watcher with a safe Windows check (only copy mode used it).
- Running `blaze_poll.py` commands in a Windows console now forces UTF-8 output, so Telugu/Hindi titles cannot crash them.

## Dashboard and report page (v9.2)
- Open `http://<pc-name>:8080` from another PC, sign in, check the cards and the story list; open one story with View details.
- Open `Tool vs desk report` from the dashboard, and check `data\reports\agreement_YYYYMMDD.html` appears and updates about once a minute while the poller runs.
