#!/bin/bash
# One-time Mac settings for an always-on machine (asks for your password once):
sudo pmset -a sleep 0 disksleep 0 displaysleep 10 autorestart 1 womp 1
echo "Never sleep, restart automatically after a power failure, wake for network access."
echo "Also set (System Settings): Users & Groups > Automatic login = the dedicated user  (not possible while FileVault is on),"
echo "and Date & Time = the newsroom's time zone."
