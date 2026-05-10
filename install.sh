#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
set -e

echo "╔══════════════════════════════════════╗"
echo "║   Protectado — Installation          ║"
echo "║   Agent IA + nono sandbox            ║"
echo "╚══════════════════════════════════════╝"

WORKDIR=$(pwd)
USER_NAME=$(whoami)

# 1. Dépendances système
echo ""
echo "→ [1/7] Dépendances système..."
sudo apt update -qq
sudo apt install -y python3-pip python3-venv arp-scan curl wget

# 2. nono via .deb (GitHub Releases)
echo ""
echo "→ [2/7] Installation de nono (sandbox kernel)..."

if ! command -v nono &> /dev/null; then
  NONO_VERSION=$(curl -sI https://github.com/always-further/nono/releases/latest | grep -i location | grep -oP 'v\K[0-9.]+')
  NONO_ARCH=$(dpkg --print-architecture)
  echo "   Version : $NONO_VERSION ($NONO_ARCH)"
  wget -q "https://github.com/always-further/nono/releases/download/v${NONO_VERSION}/nono-cli_${NONO_VERSION}_${NONO_ARCH}.deb"
  sudo dpkg -i "nono-cli_${NONO_VERSION}_${NONO_ARCH}.deb"
  rm -f "nono-cli_${NONO_VERSION}_${NONO_ARCH}.deb"
  echo "   nono installé ✓"
else
  echo "   nono déjà installé ✓"
fi

NONO_BIN=$(which nono)

# 3. Environnement Python
echo ""
echo "→ [3/7] Environnement Python..."
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 4. Pi-hole
echo ""
if ! command -v pihole &> /dev/null; then
  echo "→ [4/7] Pi-hole non détecté — installation..."
  curl -sSL https://install.pi-hole.net | bash
else
  echo "→ [4/7] Pi-hole déjà installé ✓"
fi

# 5. File d'actions (permissions restreintes)
echo ""
echo "→ [5/7] File d'actions sécurisée..."
# Le répertoire appartient à l'agent (écriture) et root peut lire (il est root de toute façon)
# Mode 700 : seul l'owner (agent) peut écrire ; root peut toujours accéder
sudo mkdir -p /tmp/fw-queue
sudo chown "$USER_NAME":"$USER_NAME" /tmp/fw-queue
sudo chmod 700 /tmp/fw-queue
sudo touch /var/log/protectado-runner.log
sudo chown root:root /var/log/protectado-runner.log
sudo chmod 640 /var/log/protectado-runner.log
echo "   /tmp/fw-queue sécurisé ✓"

# 6. Services systemd
echo ""
echo "→ [6/7] Services systemd..."

# Générer le profil nono avec le bon WORKDIR
sed -e "s|__WORKDIR__|$WORKDIR|g" \
    protectado-agent.json > /tmp/protectado-agent.json
sudo mv /tmp/protectado-agent.json "$WORKDIR/protectado-agent.json"

# Générer les services
sed -e "s|__USER__|$USER_NAME|g" \
    -e "s|__WORKDIR__|$WORKDIR|g" \
    -e "s|nono run|$NONO_BIN run|g" \
    protectado-agent.service > /tmp/protectado-agent.service

sed -e "s|__WORKDIR__|$WORKDIR|g" \
    protectado-runner.service > /tmp/protectado-runner.service

sudo mv /tmp/protectado-agent.service  /etc/systemd/system/protectado-agent.service
sudo mv /tmp/protectado-runner.service /etc/systemd/system/protectado-runner.service

sudo systemctl daemon-reload
sudo systemctl enable protectado-runner protectado-agent
echo "   Services systemd configurés ✓"

# 7. Cron quotidien (rapport + classification)
echo ""
echo "→ [7/7] Cron quotidien (rapport 23h)..."
CRON_JOB="0 23 * * * $USER_NAME $WORKDIR/.venv/bin/python $WORKDIR/daily_report.py >> /var/log/protectado-daily.log 2>&1"
CRON_FILE="/etc/cron.d/protectado-daily"
echo "$CRON_JOB" | sudo tee "$CRON_FILE" > /dev/null
sudo chmod 644 "$CRON_FILE"
echo "   Cron configuré → $CRON_FILE ✓"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║          Installation OK !           ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Architecture :"
echo "  [nono sandbox]  dashboard.py (agent + API)  → /tmp/fw-queue/"
echo "  [root]          action_runner.py            ← /tmp/fw-queue/ → iptables/pihole"
echo "  [cron 23h]      daily_report.py             → classification + rapport"
echo ""
echo "Prochaines étapes :"
echo "  1. sudo systemctl start protectado-runner protectado-agent"
echo "  2. Ouvrir http://$(hostname -I | awk '{print $1}'):8080"
echo "  3. Suivre l'assistant de configuration (wizard)"
echo "  4. Assigner les appareils depuis la page Dispositifs"
echo ""
echo "Logs :"
echo "  sudo journalctl -fu protectado-agent"
echo "  sudo journalctl -fu protectado-runner"
echo "  tail -f /var/log/protectado-daily.log"
echo ""
