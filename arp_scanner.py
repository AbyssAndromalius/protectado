# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
import subprocess
import re

# (type, [mots-clés vendor lowercase])  — premier match gagne
_VENDOR_TYPES = [
    ("phone",    ["apple", "iphone", "samsung", "xiaomi", "huawei", "oppo",
                  "fn-link", "fn link", "motorola", "nokia", "murata",
                  "azurewave", "alps alpine", "quanta computer"]),
    ("computer", ["asustek", "asus", "hp inc", "hewlett", "dell", "lenovo",
                  "acer", "msi ", "gigabyte", "intel corp", "raspberry pi",
                  "microsoft", "apple"]),
    ("gaming",   ["nintendo", "sony interactive", "valve", "xbox"]),
    ("printer",  ["brother", "canon", "epson", "xerox", "lexmark", "kyocera"]),
    ("router",   ["tp-link", "netgear", "ubiquiti", "cisco", "linksys",
                  "d-link", "zyxel", "arris", "technicolor"]),
    ("tv",       ["lg electronics", "hisense", "tcl", "vizio", "roku",
                  "sony", "philips"]),
    ("iot",      ["ecobee", "nest", "espressif", "tuya", "ikea", "signify",
                  "belkin", "amazon", "shenzhen"]),
]


def _guess_device_type(vendor: str, mac: str) -> str:
    # MAC localement administrée → téléphone en mode confidentialité MAC
    if mac and len(mac) >= 2:
        try:
            if int(mac.split(":")[0], 16) & 0x02:
                return "phone"
        except ValueError:
            pass
    v = vendor.lower()
    for device_type, keywords in _VENDOR_TYPES:
        if any(k in v for k in keywords):
            return device_type
    return "unknown"


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
                ["arp-scan", "--localnet", "--quiet"],
                capture_output=True, text=True, timeout=30
            )
            devices = []
            for line in result.stdout.splitlines():
                # Format : 192.168.0.x  aa:bb:cc:dd:ee:ff  Constructeur
                parts = line.split("\t")
                if len(parts) >= 2 and re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
                    mac = parts[1].strip() if len(parts) > 1 else ""
                    vendor = parts[2].strip() if len(parts) > 2 else ""
                    devices.append({
                        "ip": parts[0].strip(),
                        "mac": mac,
                        "vendor": vendor,
                        "device_type": _guess_device_type(vendor, mac),
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
