# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
"""
action_runner.py — Processus privilégié (root) hors sandbox nono.

Rôle : lire la file d'actions écrite par dashboard.py (sandboxé)
       et exécuter les opérations Pi-hole qui nécessitent une session root/root.

Architecture :
  Pi-hole est le seul mécanisme de blocage réseau.
  Le Pi n'est pas un routeur — iptables FORWARD n'a aucun effet dans
  un déploiement DNS-only (Pi-hole sur RPi, routeur WiFi consumer).
  Toute la politique d'accès passe par les groupes Pi-hole.

Ce processus est volontairement simple et auditable.
Il ne fait QUE ce qu'on lui demande explicitement.
"""

import ipaddress
import json
import os
import re
import sys
import time
import glob
import logging
from datetime import datetime

from paths import CONFIG_PATH as _CONFIG_PATH, ACTION_QUEUE_DIR

# Instance Pi-hole persistante — évite de recréer une session à chaque action
_pihole_api = None

def get_pihole_api():
    global _pihole_api
    if _pihole_api is None:
        with open(_CONFIG_PATH) as f:
            config = json.load(f)
        from pihole_api import PiHoleAPI
        _pihole_api = PiHoleAPI(config["pihole"]["host"], config["pihole"]["password"])
    return _pihole_api

LOG_FILE = "/var/log/protectado-runner.log"
POLL_INTERVAL = 2        # secondes
ACTION_MAX_AGE = 300     # rejeter les actions > 5 min (évite replay d'actions figées)
CLEANUP_INTERVAL = 3600  # nettoyage des fichiers .error/.stale toutes les heures

_last_cleanup = 0.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [runner] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Validation des entrées                                             #
# ------------------------------------------------------------------ #

def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


_ALLOWED_MODES = {"blocked", "work", "permissive"}

def _valid_mode(mode: str) -> bool:
    return mode in _ALLOWED_MODES


_ALLOWED_PROFILES_RE = re.compile(r'^[a-z0-9_]{1,64}$')

def _valid_profile(profile: str) -> bool:
    return bool(_ALLOWED_PROFILES_RE.match(profile))


# ------------------------------------------------------------------ #
#  Exécuteur unique : changement de mode Pi-hole                     #
# ------------------------------------------------------------------ #

def apply_pihole_mode(args: dict):
    """
    Bascule un profil vers le bon groupe Pi-hole selon le mode/slot.
    Appelé par monitor.py à chaque changement de slot ET pour les
    blocages/déblocages manuels (chat parent, override planning...).

    Modes :
      blocked    → groupe alice-blocked (wildcard DNS .*  → tout bloqué)
      work       → groupe alice-work    (blacklist entertainment+social)
      permissive → groupe alice-permissive (blacklist adult seulement)
    """
    profile    = args.get("profile", "")
    mode       = args.get("mode", "")
    blacklist  = args.get("blacklist", [])
    device_ips = args.get("device_ips", [])

    if not _valid_profile(profile):
        log.error(f"apply_pihole_mode refusé — profil invalide : {profile!r}")
        return
    if not _valid_mode(mode):
        log.error(f"apply_pihole_mode refusé — mode invalide : {mode!r}")
        return

    # Valider les IPs de la liste
    device_ips = [ip for ip in device_ips if _valid_ip(ip)]

    log.info(f"Pi-hole : {profile} → mode {mode} ({len(device_ips)} appareils)")

    try:
        api = get_pihole_api()
        ok = api.switch_profile_mode(
            profile_name=profile,
            mode=mode,
            device_ips=device_ips,
            blacklist=None if mode == "blocked" else blacklist
        )

        if not ok:
            # Groupes Pi-hole absents (premier démarrage ou reset) — setup + retry
            log.info("Groupes Pi-hole introuvables — setup initial...")
            with open(_CONFIG_PATH) as f:
                config = json.load(f)
            api.setup_profiles(config["profiles"])
            ok = api.switch_profile_mode(
                profile_name=profile,
                mode=mode,
                device_ips=device_ips,
                blacklist=None if mode == "blocked" else blacklist
            )

        if ok:
            log.info(f"Mode {mode.upper()} appliqué pour {profile}")
        else:
            log.warning(f"Échec application mode {mode} pour {profile}")

    except Exception as e:
        log.error(f"Erreur apply_pihole_mode : {e}")


HANDLERS = {
    "apply_pihole_mode": apply_pihole_mode,
}


def _cleanup_stale_files():
    """Supprime les fichiers .error et .stale de plus d'une heure."""
    for ext in ("*.error", "*.stale"):
        for path in glob.glob(os.path.join(ACTION_QUEUE_DIR, ext)):
            try:
                if time.time() - os.path.getmtime(path) > CLEANUP_INTERVAL:
                    os.remove(path)
                    log.info(f"Nettoyage : {os.path.basename(path)}")
            except OSError:
                pass


# ------------------------------------------------------------------ #
#  Boucle principale                                                  #
# ------------------------------------------------------------------ #

def process_action_file(path: str):
    try:
        with open(path) as f:
            payload = json.load(f)

        action    = payload.get("action")
        args      = payload.get("args", {})
        queued_at = payload.get("queued_at", "")

        # Rejeter les actions trop anciennes (replay protection)
        if queued_at:
            try:
                age = (datetime.now() - datetime.fromisoformat(queued_at)).total_seconds()
                if age > ACTION_MAX_AGE:
                    log.warning(f"Action expirée ({age:.0f}s > {ACTION_MAX_AGE}s) — ignorée : {path}")
                    os.rename(path, path + ".stale")
                    return
            except ValueError:
                pass  # queued_at mal formé → on continue (best effort)

        if action not in HANDLERS:
            log.warning(f"Action inconnue '{action}' dans {path} — ignorée")
        else:
            log.info(f"Exécution : {action}({args}) [queued {queued_at}]")
            HANDLERS[action](args)

        os.remove(path)

    except Exception as e:
        log.error(f"Erreur traitement {path} : {e}")
        # Renommer pour éviter une boucle infinie
        os.rename(path, path + ".error")


def main():
    if os.geteuid() != 0:
        log.error("action_runner.py doit tourner en root (sudo)")
        sys.exit(1)

    os.makedirs(ACTION_QUEUE_DIR, exist_ok=True)
    try:
        import grp
        gid = grp.getgrnam("protectado-queue").gr_gid
        os.chown(ACTION_QUEUE_DIR, 0, gid)
        os.chmod(ACTION_QUEUE_DIR, 0o2770)  # setgid : les fichiers créés héritent du groupe
    except KeyError:
        os.chmod(ACTION_QUEUE_DIR, 0o700)
        log.warning("Groupe protectado-queue introuvable — queue accessible en root uniquement")
    log.info(f"Protectado action runner démarré — surveillance {ACTION_QUEUE_DIR}")

    while True:
        global _last_cleanup
        now_ts = time.time()
        if now_ts - _last_cleanup > CLEANUP_INTERVAL:
            _cleanup_stale_files()
            _last_cleanup = now_ts

        files = sorted(glob.glob(os.path.join(ACTION_QUEUE_DIR, "action-*.json")))
        for f in files:
            process_action_file(f)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
