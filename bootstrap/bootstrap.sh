#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
# bootstrap.sh — Installation complète de Protectado sur Raspberry Pi vierge
#
# Usage (depuis le Pi, en SSH) :
#   curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
#
# Prérequis :
#   - Raspberry Pi OS Lite (Bookworm 64-bit recommandé)
#   - WiFi configuré et actif (via Raspberry Pi Imager)
#   - SSH actif

set -euo pipefail
trap 'echo ""; echo "❌  Erreur à la ligne $LINENO — arrêt."; echo ""; tail -5 "$LOG_FILE" 2>/dev/null | sed "s/^/    /"; echo ""; echo "    Logs complets : $LOG_FILE"; exit 1' ERR

# ── Configuration ────────────────────────────────────────────────────────────
REPO_URL="https://code.barbed.fr/abyss/protectado.git"
BRANCH="main"
INSTALL_DIR="/opt/protectado"
LOG_FILE="/var/log/protectado-bootstrap.log"
INFO_FILE="/tmp/fw-setup-info.txt"
FW_PORT=8080
BACKUP_DIR="/opt/protectado-backup-$(date '+%Y%m%d-%H%M%S')"

# Utilisateur propriétaire des fichiers (celui qui a lancé sudo)
REAL_USER="${SUDO_USER:-root}"

# ── Helpers ──────────────────────────────────────────────────────────────────
log()  { echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG_FILE"; }
ok()   { log "   ✓ $*"; }
step() { echo ""; log "→ [$1/$TOTAL_STEPS] $2"; }
TOTAL_STEPS=6

# ── Détection installation existante ─────────────────────────────────────────
# Une installation réelle a un venv Python, pas seulement un dépôt git cloné.

detect_existing() {
  systemctl is-active  --quiet protectado-agent 2>/dev/null && return 0
  systemctl is-enabled --quiet protectado-agent 2>/dev/null && return 0
  [ -d "$INSTALL_DIR/.venv" ] && return 0
  return 1
}

run_update() {
  echo ""
  echo "╔══════════════════════════════════════════════════╗"
  echo "║     Protectado — Installation existante         ║"
  echo "║               Mise à jour en cours...           ║"
  echo "╚══════════════════════════════════════════════════╝"
  echo ""
  log "Installation existante détectée — passage en mode mise à jour"

  cd "$INSTALL_DIR"
  LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

  # Sauvegarde datée dans un répertoire persistant (hors /tmp)
  mkdir -p "$BACKUP_DIR"
  [ -f "$INSTALL_DIR/config.json" ]    && cp "$INSTALL_DIR/config.json"    "$BACKUP_DIR/config.json"   && ok "config.json    → $BACKUP_DIR"
  [ -f "$INSTALL_DIR/protectado.db" ] && cp "$INSTALL_DIR/protectado.db" "$BACKUP_DIR/protectado.db" && ok "protectado.db → $BACKUP_DIR"

  # Mise à jour du code
  log "   Récupération des mises à jour..."
  if git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
    REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
    if [ -n "$REMOTE" ] && [ "$LOCAL" = "$REMOTE" ]; then
      ok "Déjà à jour (${LOCAL:0:8})"
    else
      if git checkout "$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
        git pull origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" \
          || log "   ⚠ pull échoué — code local conservé"
        ok "Code mis à jour : ${LOCAL:0:8} → ${REMOTE:0:8}"
      else
        log "   ⚠ Branche '$BRANCH' introuvable — branche actuelle conservée"
      fi
    fi
  else
    log "   ⚠ fetch échoué (réseau ?) — utilisation du code local"
  fi

  # Restaurer config.json (jamais écrasé par git)
  [ -f "$BACKUP_DIR/config.json" ] && cp "$BACKUP_DIR/config.json" "$INSTALL_DIR/config.json"

  # Dépendances Python
  log "   Mise à jour des dépendances Python..."
  "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade -r "$INSTALL_DIR/requirements.txt" 2>&1 | tee -a "$LOG_FILE"
  ok "Dépendances Python"

  # Migration base de données
  cd "$INSTALL_DIR"
  .venv/bin/python -c "import database; database.init_db()" 2>&1 | tee -a "$LOG_FILE"
  ok "Migration base de données"

  # Régénérer les services systemd et le profil nono (applique les changements du repo)
  log "   Mise à jour des services systemd et profil nono..."
  NONO_BIN=$(command -v nono 2>/dev/null || echo "nono")
  sed -e "s|__USER__|$REAL_USER|g" \
      -e "s|__WORKDIR__|$INSTALL_DIR|g" \
      -e "s|nono run|$NONO_BIN run|g" \
      "$INSTALL_DIR/protectado-agent.service" \
      > /etc/systemd/system/protectado-agent.service
  sed -e "s|__WORKDIR__|$INSTALL_DIR|g" \
      "$INSTALL_DIR/protectado-runner.service" \
      > /etc/systemd/system/protectado-runner.service
  mkdir -p /etc/protectado
  sed -e "s|__WORKDIR__|$INSTALL_DIR|g" \
      "$INSTALL_DIR/protectado-agent.json" \
      > /etc/protectado/agent.json
  chmod 640 /etc/protectado/agent.json
  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  ok "Services systemd et profil nono mis à jour"

  # Mise à jour du cron
  chmod +x "$INSTALL_DIR/bootstrap/arp-scan.sh"
  step5_autoupdate

  # Redémarrage
  log "   Redémarrage des services..."
  systemctl restart protectado-runner protectado-agent >> "$LOG_FILE" 2>&1
  sleep 5

  # Vérification + rollback si échec
  if ! systemctl is-active --quiet protectado-agent; then
    log "⚠  L'agent n'a pas redémarré — rollback vers ${LOCAL:0:8}..."
    cd "$INSTALL_DIR"
    git reset --hard --quiet "$LOCAL" >> "$LOG_FILE" 2>&1
    [ -f "$BACKUP_DIR/config.json" ]   && cp "$BACKUP_DIR/config.json"   "$INSTALL_DIR/config.json"
    [ -f "$BACKUP_DIR/protectado.db" ] && cp "$BACKUP_DIR/protectado.db" "$INSTALL_DIR/protectado.db"
    .venv/bin/python -c "import database; database.init_db()" >> "$LOG_FILE" 2>&1
    systemctl restart protectado-runner protectado-agent >> "$LOG_FILE" 2>&1
    sleep 3
    if systemctl is-active --quiet protectado-agent; then
      ok "Rollback réussi — retour à ${LOCAL:0:8}"
    else
      log "❌  Rollback échoué — intervention manuelle requise"
      log "    journalctl -u protectado-agent -n 50"
    fi
    exit 1
  fi

  ok "Services redémarrés"

  LOCAL_IP=$(hostname -I | awk '{print $1}')
  echo ""
  echo "╔══════════════════════════════════════════════════╗"
  echo "║          Protectado mis à jour !                ║"
  echo "╚══════════════════════════════════════════════════╝"
  echo ""
  echo "  Dashboard  →  http://$LOCAL_IP:$FW_PORT"
  echo ""
  echo "  Sauvegarde →  $BACKUP_DIR"
  echo "  Logs       →  $LOG_FILE"
  echo ""
}

check_root() {
  if [ "$EUID" -ne 0 ]; then
    echo "Ce script doit être exécuté avec sudo."
    echo "Usage : curl -sSL <url>/bootstrap/bootstrap.sh | sudo bash"
    exit 1
  fi
}

detect_network() {
  # Préférer Ethernet (plus stable pour un serveur permanent)
  IFACE=""
  for candidate in eth0 eth1 enp1s0 enp2s0 end0; do
    if ip link show "$candidate" 2>/dev/null | grep -q "state UP"; then
      IFACE="$candidate"
      break
    fi
  done
  # Fallback : interface portant la route par défaut (WiFi ou autre)
  if [ -z "$IFACE" ]; then
    IFACE=$(ip route show default 2>/dev/null | awk '/default/{print $5}' | head -1)
  fi
  IFACE="${IFACE:-wlan0}"

  IPV4=$(ip route get 8.8.8.8 2>/dev/null | awk '/src/{print $7}' | head -1)
  IPV4="${IPV4:-192.168.1.1}"

  CONN_TYPE="WiFi"
  [[ "$IFACE" == eth* || "$IFACE" == en* ]] && CONN_TYPE="Ethernet"
  log "   Interface : $IFACE ($CONN_TYPE) — IP : $IPV4"
}

# ── Étape 1 : Dépendances système ────────────────────────────────────────────
step1_system() {
  step 1 "Dépendances système"
  apt-get update -qq >> "$LOG_FILE" 2>&1
  apt-get install -y \
    git python3-pip python3-venv \
    arp-scan curl wget openssl \
    unattended-upgrades apt-listchanges \
    >> "$LOG_FILE" 2>&1
  ok "Paquets installés"

  # CAP_NET_RAW sur arp-scan — permet le scan réseau sans root
  setcap cap_net_raw+ep "$(which arp-scan)" >> "$LOG_FILE" 2>&1
  ok "cap_net_raw → arp-scan"

  # Mises à jour de sécurité automatiques (patches OS uniquement)
  dpkg-reconfigure -f noninteractive unattended-upgrades >> "$LOG_FILE" 2>&1
  ok "unattended-upgrades activé"
}

# ── Étape 2 : Pi-hole ────────────────────────────────────────────────────────
step2_pihole() {
  step 2 "Pi-hole"

  if command -v pihole &>/dev/null; then
    # Vérifier que c'est bien Pi-hole v6 (l'API REST n'existe qu'en v6)
    PIHOLE_VER=$(pihole version 2>/dev/null | grep -oP '(?:Pi-hole|Core) version(?: is)? v\K[0-9]+' | head -1 || echo "0")
    if [ "$PIHOLE_VER" -lt 6 ] 2>/dev/null; then
      echo "❌  Pi-hole v$PIHOLE_VER détecté — Protectado requiert Pi-hole v6."
      echo "    Mettez à jour Pi-hole : pihole -up"
      exit 1
    fi
    ok "Pi-hole v$PIHOLE_VER déjà installé — ignoré"
    return
  fi

  detect_network

  # Pré-configuration pour installation non-interactive
  mkdir -p /etc/pihole
  cat > /etc/pihole/setupVars.conf <<EOF
PIHOLE_INTERFACE=$IFACE
IPV4_ADDRESS=$IPV4/24
IPV6_ADDRESS=
PIHOLE_DNS_1=8.8.8.8
PIHOLE_DNS_2=1.1.1.1
QUERY_LOGGING=true
INSTALL_WEB_SERVER=true
INSTALL_WEB_INTERFACE=true
LIGHTTPD_ENABLED=true
CACHE_SIZE=10000
DNS_FQDN_REQUIRED=false
DNS_BOGUS_PRIV=true
DNSMASQ_LISTENING=local
BLOCKING_ENABLED=true
EOF
  ok "Configuration Pi-hole préparée"

  log "   Installation Pi-hole (peut prendre 2-3 minutes)..."
  curl -sSL https://install.pi-hole.net | bash /dev/stdin --unattended >> "$LOG_FILE" 2>&1
  ok "Pi-hole installé"

  # Générer un mot de passe admin aléatoire
  PIHOLE_PASS=$(openssl rand -base64 16 | tr -dc 'a-zA-Z0-9' | head -c 20)
  pihole setpassword "$PIHOLE_PASS" >> "$LOG_FILE" 2>&1
  echo "PIHOLE_PASSWORD=$PIHOLE_PASS" >> "$INFO_FILE"
  ok "Mot de passe Pi-hole défini (voir $INFO_FILE)"
}

# ── Étape 3 : Protectado ────────────────────────────────────────────────────
step3_protectado() {
  step 3 "Protectado"

  if [ -d "$INSTALL_DIR/.git" ]; then
    log "   Mise à jour depuis git..."
    if git -C "$INSTALL_DIR" fetch origin 2>&1 | tee -a "$LOG_FILE"; then
      if git -C "$INSTALL_DIR" checkout "$BRANCH" 2>&1 | tee -a "$LOG_FILE"; then
        git -C "$INSTALL_DIR" pull origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" \
          || log "   ⚠ pull échoué — code local conservé"
        ok "Dépôt mis à jour (branche $BRANCH)"
      else
        log "   ⚠ Branche '$BRANCH' introuvable — branche actuelle conservée"
        ok "Dépôt prêt"
      fi
    else
      log "   ⚠ fetch échoué (réseau ?) — utilisation du code local"
      ok "Dépôt prêt (hors ligne)"
    fi
  else
    log "   Clonage du dépôt..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1 | tee -a "$LOG_FILE"
    ok "Dépôt cloné"
  fi

  # nono (sandbox kernel pour l'agent IA)
  if ! command -v nono &>/dev/null; then
    log "   Installation de nono..."
    NONO_VER=$(curl -sI https://github.com/always-further/nono/releases/latest \
      | grep -i location | grep -oP 'v\K[0-9.]+' || echo "")
    if [ -n "$NONO_VER" ]; then
      NONO_ARCH=$(dpkg --print-architecture)
      NONO_DEB="/tmp/nono-cli_${NONO_VER}_${NONO_ARCH}.deb"
      wget -q -O "$NONO_DEB" \
        "https://github.com/always-further/nono/releases/download/v${NONO_VER}/nono-cli_${NONO_VER}_${NONO_ARCH}.deb"
      dpkg -i "$NONO_DEB" >> "$LOG_FILE" 2>&1
      rm -f "$NONO_DEB"
      ok "nono installé"
    else
      log "   ⚠ nono introuvable — l'agent fonctionnera sans sandbox"
    fi
  else
    ok "nono déjà installé"
  fi

  # Environnement Python
  log "   Création du venv Python..."
  python3 -m venv "$INSTALL_DIR/.venv" 2>&1 | tee -a "$LOG_FILE"
  "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip 2>&1 | tee -a "$LOG_FILE"
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" 2>&1 | tee -a "$LOG_FILE"
  ok "Environnement Python prêt"

  # Initialiser la base de données
  cd "$INSTALL_DIR"
  .venv/bin/python -c "import database; database.init_db()" 2>&1 | tee -a "$LOG_FILE"
  ok "Base de données initialisée"

  # Ajuster les permissions après création de tous les fichiers
  chown -R "$REAL_USER:$REAL_USER" "$INSTALL_DIR"
  ok "Permissions ajustées ($REAL_USER)"
}

# ── Étape 4 : Services systemd ───────────────────────────────────────────────
step4_services() {
  step 4 "Services systemd"

  groupadd -f protectado-queue
  usermod -aG protectado-queue "$REAL_USER"
  touch /var/log/protectado-runner.log
  ok "Groupe protectado-queue configuré"

  NONO_BIN=$(command -v nono 2>/dev/null || echo "nono")

  sed -e "s|__USER__|$REAL_USER|g" \
      -e "s|__WORKDIR__|$INSTALL_DIR|g" \
      -e "s|nono run|$NONO_BIN run|g" \
      "$INSTALL_DIR/protectado-agent.service" \
      > /etc/systemd/system/protectado-agent.service

  sed -e "s|__WORKDIR__|$INSTALL_DIR|g" \
      "$INSTALL_DIR/protectado-runner.service" \
      > /etc/systemd/system/protectado-runner.service

  mkdir -p /etc/protectado
  sed -e "s|__WORKDIR__|$INSTALL_DIR|g" \
      "$INSTALL_DIR/protectado-agent.json" \
      > /etc/protectado/agent.json
  chmod 640 /etc/protectado/agent.json

  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  systemctl enable protectado-runner protectado-agent >> "$LOG_FILE" 2>&1
  systemctl start protectado-runner protectado-agent >> "$LOG_FILE" 2>&1
  sleep 3

  STATUS_RUNNER=$(systemctl is-active protectado-runner || echo "inactive")
  STATUS_AGENT=$(systemctl is-active protectado-agent   || echo "inactive")
  ok "protectado-runner : $STATUS_RUNNER"
  ok "protectado-agent  : $STATUS_AGENT"

  if [ "$STATUS_AGENT" != "active" ]; then
    log "   ⚠ L'agent n'a pas démarré — vérifiez : journalctl -u protectado-agent"
  fi
}

# ── Étape 5 : Mises à jour automatiques ─────────────────────────────────────
step5_autoupdate() {
  step 5 "Mises à jour automatiques"

  chmod +x "$INSTALL_DIR/bootstrap/auto-update.sh"

  chmod +x "$INSTALL_DIR/bootstrap/arp-scan.sh"

  cat > /etc/cron.d/protectado <<EOF
# Protectado — auto-update chaque nuit à 3h00
0 3 * * * root $INSTALL_DIR/bootstrap/auto-update.sh >> /var/log/fw-update.log 2>&1

# Pi-hole — mise à jour chaque dimanche à 4h00
0 4 * * 0 root pihole -up >> /var/log/fw-update.log 2>&1

# Rapport journalier à 7h00
0 7 * * * $REAL_USER $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/daily_report.py >> /var/log/protectado-report.log 2>&1

# Nettoyage timeline DNS (conservation 7 jours) — chaque dimanche à 2h00
0 2 * * 0 root $INSTALL_DIR/.venv/bin/python -c "import sys; sys.path.insert(0,'$INSTALL_DIR'); import database; database.purge_old_timeline()" >> /var/log/protectado-report.log 2>&1

# Scan ARP toutes les 5 minutes — résultat lu par l'agent via /tmp/fw-queue/
*/5 * * * * root $INSTALL_DIR/bootstrap/arp-scan.sh
EOF
  chmod 644 /etc/cron.d/protectado
  ok "Crons configurés"
}

# ── Étape 6 : Récapitulatif ──────────────────────────────────────────────────
step6_summary() {
  step 6 "Installation terminée"

  LOCAL_IP=$(hostname -I | awk '{print $1}')
  DASHBOARD_URL="http://$LOCAL_IP:$FW_PORT"

  echo ""
  echo "╔══════════════════════════════════════════════════╗"
  echo "║          Protectado installé avec succès !      ║"
  echo "╚══════════════════════════════════════════════════╝"
  echo ""
  echo "  Dashboard  →  $DASHBOARD_URL"
  echo ""

  if [ -f "$INFO_FILE" ]; then
    echo "  ┌─ Informations de configuration ─────────────────"
    while IFS='=' read -r key val; do
      printf "  │  %-22s %s\n" "$key :" "$val"
    done < "$INFO_FILE"
    echo "  └──────────────────────────────────────────────────"
    echo ""
    echo "  → Gardez ces informations pour le wizard de configuration."
  fi

  echo ""
  echo "  Prochaine étape : ouvrez $DASHBOARD_URL depuis"
  echo "  n'importe quel appareil du réseau et suivez le wizard."
  echo ""
  echo "  Logs bootstrap : $LOG_FILE"
  echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────
main() {
  check_root
  touch "$LOG_FILE"

  # Détection : installation existante → mise à jour, sinon → installation initiale
  if detect_existing; then
    run_update
    exit 0
  fi

  rm -f "$INFO_FILE"

  echo ""
  echo "╔══════════════════════════════════════════════════╗"
  echo "║        Protectado — Bootstrap Raspberry Pi      ║"
  echo "╚══════════════════════════════════════════════════╝"
  echo ""
  log "Début de l'installation — $(date)"

  step1_system
  step2_pihole
  step3_protectado
  step4_services
  step5_autoupdate
  step6_summary
}

main "$@"
