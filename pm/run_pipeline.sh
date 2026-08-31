#!/bin/bash
# Wait for the market fetch to finish, then pull candles for a stratified sample.
cd "$(dirname "$0")"
while pgrep -f "kalshi_fetch.py markets" > /dev/null; do sleep 20; done
echo "markets done: $(wc -l < data/markets_raw.jsonl) rows"
SAMPLE=20000 RATE=6 python3 kalshi_fetch.py candles
echo "=== candles complete, running wedge estimation ==="
python3 wedge.py > wedge_report.txt 2>&1
echo "done -> wedge_report.txt"
