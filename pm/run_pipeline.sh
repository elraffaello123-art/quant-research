#!/bin/bash
# Pull candles for a stratified sample, then estimate the wedge.
# caffeinate: this is a ~1h network job and a sleeping Mac silently stalls it.
cd "$(dirname "$0")"
SAMPLE=20000 RATE=8 WORKERS=8 caffeinate -i python3 kalshi_fetch.py candles
echo "=== candles complete, running wedge estimation ==="
caffeinate -i python3 wedge.py > wedge_report.txt 2>&1
echo "done -> wedge_report.txt"
