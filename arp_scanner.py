# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
import subprocess
import re


class ARPScanner:
    def __init__(self, subnet: str):
        self.subnet = subnet

    def scan(self) -> list[dict]:
        """
        Retourne la liste des appareils actifs sur le réseau local.
        Nécessite : sudo apt install arp-scan
        """
        try:
            result = subprocess.run(
                ["sudo", "arp-scan", "--localnet", "--quiet"],
                capture_output=True, text=True, timeout=30
            )
            devices = []
            for line in result.stdout.splitlines():
                # Format : 192.168.0.x  aa:bb:cc:dd:ee:ff  Constructeur
                parts = line.split("\t")
                if len(parts) >= 2 and re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
                    devices.append({
                        "ip": parts[0].strip(),
                        "mac": parts[1].strip() if len(parts) > 1 else "",
                        "vendor": parts[2].strip() if len(parts) > 2 else ""
                    })
            return devices
        except Exception as e:
            print(f"[Scanner] Erreur arp-scan : {e}")
            return self._fallback_arp()

    def _fallback_arp(self) -> list[dict]:
        """Fallback via la table ARP du système."""
        try:
            result = subprocess.run(["arp", "-n"], capture_output=True, text=True)
            devices = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3 and parts[2] != "<incomplete>":
                    devices.append({
                        "ip": parts[0],
                        "mac": parts[2],
                        "vendor": ""
                    })
            return devices
        except Exception as e:
            print(f"[Scanner] Erreur arp fallback : {e}")
            return []

    def get_active_ips(self) -> set[str]:
        return {d["ip"] for d in self.scan()}
