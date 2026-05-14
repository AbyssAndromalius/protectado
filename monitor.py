# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
"""
monitor.py — Moteur de surveillance Python pur, sans IA.

Tourne toutes les 60 secondes.
Gère les règles déterministes :
  - Couvre-feu (heure)
  - Quota YouTube (minutes)
  - Bypass DNS
  - Domaines bloqués accédés

Appelle claude_agent.py UNIQUEMENT pour les patterns inhabituels.
Coût IA : ~0 en fonctionnement normal.
"""

import json
import time
import threading
import os
from collections import deque
from datetime import datetime

from paths import CONFIG_PATH, ACTION_QUEUE_DIR
from pihole_api import PiHoleAPI
from scheduler import get_slot_at
import domain_classifier as classifier
from arp_scanner import ARPScanner
import database as db

# Seuil pour considérer un volume de requêtes comme "inhabituel"
UNUSUAL_QUERY_THRESHOLD = 50  # requêtes vers un domaine inconnu en 5 min
ESCALATE_AFTER = 3            # événements inhabituels avant escalade Claude

# Déduplication des domaines bloqués
BLOCK_WINDOW_SEC     = 600    # 10 min — une seule alerte par fenêtre
KEEPALIVE_MAX_HITS   = 4      # ≤ 4 hits/cycle (fenêtre Pi-hole 5 min) → keepalive
KEEPALIVE_MIN_CYCLES = 3      # 3 cycles consécutifs bas → silence total


_global_monitor: "ProtectadoMonitor | None" = None


def notify_monitor():
    """Réveille le monitor global immédiatement (après une écriture en DB)."""
    if _global_monitor is not None:
        _global_monitor.notify()


class ProtectadoMonitor:
    def __init__(self, config_path: str = CONFIG_PATH):
        with open(config_path) as f:
            self.config = json.load(f)

        self.pihole = PiHoleAPI(
            self.config["pihole"]["host"],
            self.config["pihole"]["password"]
        )
        self.scanner = ARPScanner(self.pihole)
        self._running = False
        self._wakeup = threading.Event()
        self._unusual_events = []  # buffer avant escalade vers Claude
        self._block_state: dict = {}   # (profile, domain) → état déduplication
        self._last_slot: dict = {}     # profile → dernier mode détecté
        self._cloudflare_cycle: int = 0  # compteur pour classification périodique

        db.init_db()

    def reload_config(self):
        """Recharge config sans redémarrer le service."""
        with open(CONFIG_PATH) as f:
            self.config = json.load(f)
        self.scanner = ARPScanner(self.pihole)

    # ------------------------------------------------------------------ #
    #  File d'actions                                                     #
    # ------------------------------------------------------------------ #

    def _queue_action(self, action: str, args: dict):
        ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
        path = os.path.join(ACTION_QUEUE_DIR, f"action-{ts}.json")
        payload = {"action": action, "args": args, "queued_at": datetime.now().isoformat()}
        with open(path, "w") as f:
            json.dump(payload, f)
        print(f"[Monitor] → {action}({args.get('ip', args.get('domain', ''))})")

    # ------------------------------------------------------------------ #
    #  Règles déterministes (sans IA)                                    #
    # ------------------------------------------------------------------ #

    def _check_schedule(self, profile_key: str, profile: dict, active_ips: set):
        """Applique le slot horaire courant — aucune IA nécessaire."""
        is_monitoring = profile.get("mode") == "monitoring"
        if is_monitoring:
            return

        # Vérifier si un override existe pour aujourd'hui
        today = datetime.now().strftime("%Y-%m-%d")
        with db.get_db() as conn:
            override = conn.execute(
                "SELECT mode FROM schedule_overrides WHERE profile=? AND date=?",
                (profile_key, today)
            ).fetchone()

        if override and override["mode"] != "normal":
            raw_mode = override["mode"]
            mode = "permissive" if raw_mode == "free" else raw_mode
            slot = {"slot_start": "00:00", "slot_end": "23:59", "mode": mode}
        else:
            slot = get_slot_at(profile_key, datetime.now())
            mode = slot["mode"]

        # Détecter un changement de slot
        prev_mode = self._last_slot.get(profile_key)
        if prev_mode != mode:
            print(f"[Monitor] {profile_key} : {prev_mode} → {mode} ({slot['slot_start']}-{slot['slot_end']})")
            self._last_slot[profile_key] = mode
            db.log_event(profile_key, "info", "",
                         f"Changement de plage : {mode} jusqu\'à {slot['slot_end']}")

            # Appliquer via Pi-hole selon le mode
            self._apply_pihole_mode(profile_key, mode)

        # Le changement de mode est entièrement géré par Pi-hole via _apply_pihole_mode.
        # Pas d'iptables — le Pi n'est pas un routeur dans le déploiement standard.

    def _apply_pihole_mode(self, profile_key: str, mode: str):
        """
        Configure Pi-hole selon le mode actif.
        Passe les IPs des appareils pour basculer leur groupe.
        """
        # Le profil monitoring n'a pas de groupes Pi-hole
        if self.config["profiles"].get(profile_key, {}).get("mode") == "monitoring":
            return

        profile = self.config["profiles"].get(profile_key, {})
        device_ips = [d["ip"] for d in profile.get("devices", [])]
        blacklist = classifier.get_active_blacklist(mode)
        self._queue_action("apply_pihole_mode", {
            "profile": profile_key,
            "mode": mode,
            "device_ips": device_ips,
            "blacklist": blacklist
        })

    def _check_blocked_domains(self, profile_key: str, profile: dict,
                                queries_by_ip: dict):
        """
        Logue les accès à des domaines bloqués avec déduplication :
        - Keepalives (≤ KEEPALIVE_MAX_HITS hits/cycle pendant KEEPALIVE_MIN_CYCLES cycles)
          → silence total, aucun log.
        - Activité réelle → un seul événement au début de chaque fenêtre de 10 min.
          Après 10 min de silence, la prochaine tentative génère un nouvel événement.
        """
        import domain_classifier as dc
        current_mode = get_slot_at(profile_key, datetime.now())["mode"]
        active_blacklist = set(dc.get_active_blacklist(current_mode))
        now = datetime.now()

        # Compter les hits par domaine root bloqué pour ce cycle
        domain_hits: dict[str, int] = {}
        for device in profile.get("devices", []):
            for domain in queries_by_ip.get(device["ip"], []):
                root = self._root_domain(domain)
                if root in active_blacklist:
                    domain_hits[root] = domain_hits.get(root, 0) + 1

        for domain, hits in domain_hits.items():
            key = (profile_key, domain)
            if key not in self._block_state:
                self._block_state[key] = {
                    "window_start": None,
                    "window_count": 0,
                    "hit_history": deque(maxlen=KEEPALIVE_MIN_CYCLES + 2),
                    "last_seen": None,
                }
            state = self._block_state[key]
            state["hit_history"].append(hits)
            state["last_seen"] = now
            history = list(state["hit_history"])

            # 1. Pas assez d'historique + trafic faible → suspendre le jugement
            if hits <= KEEPALIVE_MAX_HITS and len(history) < KEEPALIVE_MIN_CYCLES:
                continue

            # 2. Keepalive confirmé → silence total
            if (len(history) >= KEEPALIVE_MIN_CYCLES and
                    all(h <= KEEPALIVE_MAX_HITS for h in history[-KEEPALIVE_MIN_CYCLES:])):
                state["window_start"] = None
                state["window_count"] = 0
                continue

            # 3. Activité réelle — déduplication par fenêtre de 10 min
            in_window = (
                state["window_start"] is not None and
                (now - state["window_start"]).total_seconds() < BLOCK_WINDOW_SEC
            )
            if in_window:
                state["window_count"] += hits
            else:
                # Nouvelle fenêtre → un seul log
                state["window_start"] = now
                state["window_count"] = hits
                suffix = f" ({hits} tentatives)" if hits > 1 else ""
                db.log_event(
                    profile_key, "warning", domain,
                    f"Tentative d'accès à {domain} (bloqué — {current_mode}){suffix}"
                )
                print(f"[Monitor] 🚫 {profile_key} → {domain} ({hits} req, {current_mode})")

    def _check_unusual_patterns(self, profile_key: str, profile: dict,
                                 queries_by_ip: dict):
        """
        Détecte des patterns non couverts par les règles.
        Accumule dans un buffer — escalade vers Claude si seuil atteint.
        """
        # Domaines connus = ceux déjà dans la DB
        import domain_classifier as dc
        known_domains = {d["domain"] for d in dc.get_all_domains()}

        for device in profile.get("devices", []):
            ip = device["ip"]
            domain_counts = {}
            for domain in queries_by_ip.get(ip, []):
                root = self._root_domain(domain)
                domain_counts[root] = domain_counts.get(root, 0) + 1

            for domain, count in domain_counts.items():
                if domain not in known_domains and count >= UNUSUAL_QUERY_THRESHOLD:
                    event = {
                        "profile": profile_key,
                        "domain": domain,
                        "count": count,
                        "timestamp": datetime.now().isoformat()
                    }
                    self._unusual_events.append(event)
                    print(f"[Monitor] Pattern inhabituel : {domain} × {count} pour {profile_key}")

        # Escalade vers Claude si assez d'événements inhabituels
        if len(self._unusual_events) >= ESCALATE_AFTER:
            self._escalate_to_claude()

    def _escalate_to_claude(self):
        """Appelle Claude uniquement pour les patterns inhabituels."""
        try:
            from claude_agent import analyze_unusual_patterns
            analyze_unusual_patterns(self._unusual_events)
        except Exception as e:
            print(f"[Monitor] Erreur escalade Claude : {e}")
        finally:
            self._unusual_events = []

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #



    def _root_domain(self, domain: str) -> str:
        parts = domain.rstrip(".").split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else domain

    # ------------------------------------------------------------------ #
    #  Cycle principal                                                    #
    # ------------------------------------------------------------------ #

    def _check_expired_overrides(self):
        """Remet les appareils dont le mode adulte a expiré dans leur groupe normal."""
        for ip in db.get_expired_override_ips():
            profile_key = None
            for pkey, profile in self.config["profiles"].items():
                if any(d["ip"] == ip for d in profile.get("devices", [])):
                    profile_key = pkey
                    break
            db.clear_device_override(ip)
            if profile_key:
                slot = get_slot_at(profile_key, datetime.now())
                self.pihole.assign_client_to_group(ip, f"{profile_key}-{slot['mode']}")
                db.log_event(profile_key, "info", ip,
                             "Mode adulte terminé — retour profil enfant")
                print(f"[Monitor] ⏱ Override expiré : {ip} → {profile_key}-{slot['mode']}")

    def _maybe_classify_cloudflare(self):
        """Classification Cloudflare toutes les 10 minutes (cycle 60s × 10 = 10 min)."""
        self._cloudflare_cycle += 1
        if self._cloudflare_cycle < 10:
            return
        self._cloudflare_cycle = 0
        try:
            n = classifier.classify_with_cloudflare(limit=100)
            if n:
                print(f"[Monitor] Cloudflare : {n} nouveaux domaines catégorisés")
        except Exception as e:
            print(f"[Monitor] Erreur classification Cloudflare : {e}")

    def run_cycle(self):
        self._check_expired_overrides()
        self._maybe_classify_cloudflare()
        queries   = self.pihole.get_recent_queries(minutes=5)
        by_ip     = self.pihole.queries_by_client(queries)
        active_ips = self.scanner.get_active_ips()

        for pname, profile in self.config["profiles"].items():
            # Ignorer si aucun appareil configuré
            if not profile.get("devices"):
                continue
            # Incrémenter l'usage DNS + enregistrer domaine avec mode courant
            current_mode = get_slot_at(pname, datetime.now())["mode"]
            for device in profile.get("devices", []):
                for domain in by_ip.get(device["ip"], []):
                    root = self._root_domain(domain)
                    if root:
                        db.increment_usage(pname, root)
                        classifier.record_domain(root, current_mode)

            # Règles déterministes — aucun appel IA
            self._check_schedule(pname, profile, active_ips)
            self._check_blocked_domains(pname, profile, by_ip)
            self._check_unusual_patterns(pname, profile, by_ip)

    def run_once(self):
        """Pour tests."""
        self.run_cycle()

    # ------------------------------------------------------------------ #
    #  Boucle                                                             #
    # ------------------------------------------------------------------ #

    def notify(self):
        """Réveille le cycle immédiatement (appel externe après écriture en DB)."""
        self._wakeup.set()

    def start(self, interval: int = 60):
        global _global_monitor
        _global_monitor = self
        self._running = True
        print(f"[Monitor] Démarré — cycle toutes les {interval}s (sans IA)")

        def loop():
            while self._running:
                self._wakeup.clear()
                try:
                    self.run_cycle()
                except Exception as e:
                    print(f"[Monitor] Erreur cycle : {e}")
                self._wakeup.wait(timeout=interval)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()

    def stop(self):
        self._running = False
