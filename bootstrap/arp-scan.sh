#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Scan ARP — tourne en root hors sandbox, écrit dans /tmp/fw-queue/arp_scan.json
set -euo pipefail

QUEUE_DIR="/tmp/fw-queue"
OUT="$QUEUE_DIR/arp_scan.json"
TMP="$OUT.tmp"

mkdir -p "$QUEUE_DIR"

arp-scan --localnet --quiet 2>/dev/null | python3 -c "
import sys, re, json, time
devices = []
for line in sys.stdin:
    parts = line.split('\t')
    if len(parts) >= 2 and re.match(r'\d+\.\d+\.\d+\.\d+', parts[0].strip()):
        devices.append({
            'ip':     parts[0].strip(),
            'mac':    parts[1].strip() if len(parts) > 1 else '',
            'vendor': parts[2].strip() if len(parts) > 2 else '',
        })
print(json.dumps({'devices': devices, 'ts': time.time()}))
" > "$TMP" && mv "$TMP" "$OUT"
chmod 644 "$OUT"
