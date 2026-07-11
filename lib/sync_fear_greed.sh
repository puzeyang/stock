#!/usr/bin/env bash
# Pull the CNN Fear & Greed parquet cache from the VPS down to the local Mac copy.
# The VPS refreshes lib/data/fear_greed/ daily (fear-greed.timer @ 17:30 ET); this
# mirrors it so the notebooks see the latest without hitting CNN locally.
#
# NOTE: these parquets are git-TRACKED. rsync overwrites them, so git will show
# them modified after a sync — commit the fresh data manually when you want it in
# history (per the chosen "sync overwrites, commit manually" workflow).
#
# Safe to run any time — rsync only transfers changed files.
set -uo pipefail

REMOTE_DIR="oracle-ibkr:~/stock/lib/data/fear_greed/"
LOCAL_DIR="/Users/puzeyang/My Drive/dev/python/stock/lib/data/fear_greed/"
LOG="/Users/puzeyang/My Drive/dev/python/stock/lib/data/fear_greed/sync.log"

ts() { date "+%Y-%m-%d %H:%M:%S"; }
echo "[$(ts)] sync_fear_greed: start" >> "$LOG"

if /usr/bin/rsync -av --include='*.parquet' --exclude='*' \
        "$REMOTE_DIR" "$LOCAL_DIR" >> "$LOG" 2>&1; then
    echo "[$(ts)] sync_fear_greed: OK" >> "$LOG"
else
    echo "[$(ts)] sync_fear_greed: FAILED (exit $?)" >> "$LOG"
    exit 1
fi
