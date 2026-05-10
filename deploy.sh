#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
# deploy.sh — Déploiement depuis Git
# Usage : bash deploy.sh [--init] [--reset-db]
set -e

INSTALL_DIR="/opt/protectado"
BRANCH="multi-family"
REPO_URL="https://code.barbed.fr/abyss/protectado.git"

RESET_DB=false
INIT=false
for arg in "$@"; do
  case $arg in
    --init)    INIT=true ;;
    --reset-db) RESET_DB=true ;;
  esac
done

echo "╔══════════════════════════════════════╗"
echo "║   Protectado — Déploiement Git      ║"
echo "╚══════════════════════════════════════╝"

# ── Init : premier déploiement ──────────────────────────────────────
if [ "$INIT" = true ]; then
  echo "→ Installation initiale..."
  sudo apt install -y git python3-venv python3-pip arp-scan wget

  # Cloner le dépôt
  sudo git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"

  # Créer le venv
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements.txt

  # Config initiale
  cp config.json.example config.json
  echo "⚠ Édite $INSTALL_DIR/config.json avec tes clés avant de démarrer"
  echo "  puis relance : bash deploy.sh"
  exit 0
fi

# ── Mise à jour ─────────────────────────────────────────────────────
cd "$INSTALL_DIR"
echo "→ Arrêt des services..."
sudo systemctl stop protectado-agent protectado-runner 2>/dev/null || true

# Sauvegarder config
cp config.json /tmp/fw-config.backup.json
echo "→ config.json sauvegardé"

# Pull Git
echo "→ git pull origin $BRANCH..."
sudo git pull origin "$BRANCH"

# Restaurer config (jamais versionné)
cp /tmp/fw-config.backup.json config.json
echo "→ config.json restauré"

# Mettre à jour les dépendances si requirements.txt a changé
source .venv/bin/activate
pip install -q --upgrade -r requirements.txt

# Migrer la DB
if [ "$RESET_DB" = true ]; then
  echo "→ Réinitialisation de la base..."
  rm -f protectado.db
fi
python -c "import database; database.init_db(); print('→ DB OK')"

# Redémarrer
echo "→ Démarrage des services..."
sudo systemctl daemon-reload
sudo systemctl start protectado-runner protectado-agent
sleep 3

# Statut
echo ""
S_RUNNER=$(sudo systemctl is-active protectado-runner)
S_AGENT=$(sudo systemctl is-active protectado-agent)
echo "  protectado-runner : $S_RUNNER"
echo "  protectado-agent  : $S_AGENT"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║         Déploiement terminé !        ║"
echo "╚══════════════════════════════════════╝"
echo "  Dashboard → http://$(hostname -I | awk '{print $1}'):8080"
