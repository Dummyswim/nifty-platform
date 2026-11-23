#!/usr/bin/env bash
# Copies the Pine scripts, original prompts and NVS oracle into reference/ and verifies SHA-256 pins.
# Usage: bash scripts/setup-reference.sh   (override source dir with PINE_SRC=/path/to/pineColl)
set -euo pipefail
SRC="${PINE_SRC:-/Users/bchavdi/Downloads/pineColl}"
cd "$(dirname "$0")/.."
mkdir -p reference/pine reference/src reference/oracle/data reference/oracle/logs
cp "$SRC/Jun9/Balu_Zone_Scalper_v2.pine" reference/pine/
cp "$SRC/selfhosted/Nifty_VWAP_Spread_Scalper.pine" reference/pine/
cp "$SRC/NIFTY_Trading_Platform_Copilot_Prompt.md" reference/src/webapp-prompt.md
cp "$SRC/01-distance-entry-research-platform.md" reference/src/research-prompt.md
cp "$SRC/selfhosted/vwap_scalper.py" "$SRC/selfhosted/test_vwap_scalper.py" "$SRC/selfhosted/VWAP_SCALPER.md" reference/oracle/
cp "$SRC/selfhosted/data/nifty_1m.csv" reference/oracle/data/
cp "$SRC/selfhosted/logs/scalper_trades.csv" reference/oracle/logs/
cd reference
if command -v sha256sum >/dev/null 2>&1; then sha256sum -c SHA256SUMS; else shasum -a 256 -c SHA256SUMS; fi
echo "reference/ OK"
