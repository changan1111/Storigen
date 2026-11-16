#!/bin/bash
# Mounts the NAS shares under /Volumes using the credentials saved in the Mac Keychain (connect once in Finder > Go > Connect to Server and tick "Remember this password").
# Add this script as a Login Item (System Settings > General > Login Items) for the dedicated user, or run it from a launchd job.
# EDIT the two lines below to your real shares.
osascript -e 'mount volume "smb://NAS-HOSTNAME/Playout"'
osascript -e 'mount volume "smb://NITRO-HOSTNAME/ONAIR"'
# The folders then appear as /Volumes/Playout and /Volumes/ONAIR: put those paths in autoid.env (EXPORTS_DIR, NITRO_DIR).
# Nitro: connect with a READ-ONLY account. The watcher never writes there.
