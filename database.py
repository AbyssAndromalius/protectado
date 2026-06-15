# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
import sqlite3
from datetime import datetime, date, timedelta
from contextlib import contextmanager
from paths import DB_PATH

# Fenêtre de session : si deux requêtes sont séparées de moins de N minutes
# on considère que c'est la même session de visionnage
SESSION_GAP_MINUTES = 10


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS acknowledged_reports (
                event_id    INTEGER PRIMARY KEY,
                acked_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                profile   TEXT    NOT NULL,
                type      TEXT    NOT NULL,
                domain    TEXT    DEFAULT '',
                message   TEXT    DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
                date    TEXT NOT NULL,
                profile TEXT NOT NULL,
                domain  TEXT NOT NULL,
                queries INTEGER DEFAULT 0,
                PRIMARY KEY (date, profile, domain)
            );

            -- Historique horodaté des requêtes DNS par domaine/profil
            -- Utilisé pour estimer le temps de session
            CREATE TABLE IF NOT EXISTS dns_timeline (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL,
                profile   TEXT    NOT NULL,
                domain    TEXT    NOT NULL
            );

            -- Index pour accélérer les requêtes par profil/domaine/date
            CREATE INDEX IF NOT EXISTS idx_dns_timeline_lookup
                ON dns_timeline(profile, domain, timestamp);

            CREATE TABLE IF NOT EXISTS schedule_overrides (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                profile     TEXT NOT NULL,
                date        TEXT NOT NULL,
                mode        TEXT NOT NULL,
                reason      TEXT DEFAULT '',
                created_at  TEXT NOT NULL,
                UNIQUE(profile, date)
            );

            CREATE TABLE IF NOT EXISTS device_overrides (
                ip          TEXT PRIMARY KEY,
                expires_at  TEXT NOT NULL,
                taken_by    TEXT DEFAULT 'parent',
                created_at  TEXT NOT NULL
            );
        """)
        conn.commit()
    init_domains_table()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def log_event(profile: str, event_type: str, domain: str = "", message: str = ""):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (timestamp, profile, type, domain, message) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), profile, event_type, domain, message)
        )


def increment_usage(profile: str, domain: str, count: int = 1):
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    with get_db() as conn:
        # Compteur de requêtes (existant)
        conn.execute("""
            INSERT INTO daily_usage (date, profile, domain, queries)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date, profile, domain)
            DO UPDATE SET queries = queries + excluded.queries
        """, (today, profile, domain, count))

        # Timeline horodatée pour estimation du temps
        conn.execute(
            "INSERT INTO dns_timeline (timestamp, profile, domain) VALUES (?,?,?)",
            (now, profile, domain)
        )


def estimate_session_minutes(profile: str, domain: str, for_date: str = None) -> int:
    """
    Estime le temps passé sur un domaine en regroupant les requêtes DNS
    en sessions continues (gap < SESSION_GAP_MINUTES).

    Algo :
    - Trier les requêtes par timestamp
    - Si l'écart entre deux requêtes < SESSION_GAP_MINUTES → même session
    - Durée session = (dernière requête - première requête) + SESSION_GAP_MINUTES
    - Total = somme des durées de sessions
    """
    if for_date is None:
        for_date = date.today().isoformat()

    start = f"{for_date}T00:00:00"
    end   = f"{for_date}T23:59:59"

    with get_db() as conn:
        rows = conn.execute("""
            SELECT timestamp FROM dns_timeline
            WHERE profile=? AND domain=?
              AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (profile, domain, start, end)).fetchall()

    if not rows:
        return 0

    timestamps = [datetime.fromisoformat(r["timestamp"]) for r in rows]
    gap = timedelta(minutes=SESSION_GAP_MINUTES)

    total_minutes = 0
    session_start = timestamps[0]
    session_last  = timestamps[0]

    for ts in timestamps[1:]:
        if ts - session_last < gap:
            # Même session
            session_last = ts
        else:
            # Nouvelle session — comptabiliser la précédente
            duration = (session_last - session_start) + gap
            total_minutes += int(duration.total_seconds() / 60)
            session_start = ts
            session_last  = ts

    # Dernière session
    duration = (session_last - session_start) + gap
    total_minutes += int(duration.total_seconds() / 60)

    return total_minutes


def get_time_spent_today(profile: str) -> dict:
    """Retourne le temps estimé (en minutes) par domaine pour aujourd'hui."""
    today = date.today().isoformat()
    with get_db() as conn:
        domains = conn.execute("""
            SELECT DISTINCT domain FROM dns_timeline
            WHERE profile=? AND timestamp LIKE ?
        """, (profile, f"{today}%")).fetchall()

    return {
        row["domain"]: estimate_session_minutes(profile, row["domain"])
        for row in domains
    }


def get_last_dns(profile: str) -> datetime | None:
    """Retourne le timestamp de la dernière requête DNS enregistrée pour un profil."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT timestamp FROM dns_timeline WHERE profile=? ORDER BY timestamp DESC LIMIT 1",
            (profile,)
        ).fetchone()
    return datetime.fromisoformat(row["timestamp"]) if row else None


def get_usage_today(profile: str) -> dict:
    today = date.today().isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT domain, queries FROM daily_usage WHERE date=? AND profile=?",
            (today, profile)
        ).fetchall()
    return {row["domain"]: row["queries"] for row in rows}


def get_recent_events(limit: int = 50) -> list:
    _REPORT_TYPES = ('daily_report', 'weekly_report', 'monthly_report')
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE type NOT IN (?,?,?) ORDER BY timestamp DESC LIMIT ?",
            (*_REPORT_TYPES, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_reports() -> list[dict]:
    """Rapports non encore acquittés (daily, weekly, monthly)."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT e.id, e.timestamp, e.type, e.message
            FROM events e
            LEFT JOIN acknowledged_reports a ON a.event_id = e.id
            WHERE e.profile = 'global'
              AND e.type IN ('daily_report', 'weekly_report', 'monthly_report')
              AND a.event_id IS NULL
            ORDER BY e.timestamp DESC
        """).fetchall()
    return [dict(r) for r in rows]


def acknowledge_report(event_id: int):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO acknowledged_reports (event_id, acked_at) VALUES (?,?)",
            (event_id, datetime.now().isoformat())
        )


def get_events_for_profile(profile: str, limit: int = 20) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE profile=? ORDER BY timestamp DESC LIMIT ?",
            (profile, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def purge_old_timeline(days: int = 7):
    """Nettoie les entrées de timeline de plus de N jours."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        conn.execute("DELETE FROM dns_timeline WHERE timestamp < ?", (cutoff,))


def get_dns_hits(profile: str, date: str, domain: str = None) -> list:
    """
    Retourne les hits DNS horodatés pour un profil/date.
    Si domain est fourni, filtre sur ce domaine racine.
    """
    start = f"{date}T00:00:00"
    end   = f"{date}T23:59:59"
    with get_db() as conn:
        if domain:
            rows = conn.execute("""
                SELECT timestamp, domain FROM dns_timeline
                WHERE profile=? AND domain=? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            """, (profile, domain, start, end)).fetchall()
        else:
            rows = conn.execute("""
                SELECT timestamp, domain FROM dns_timeline
                WHERE profile=? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            """, (profile, start, end)).fetchall()
    return [dict(r) for r in rows]


def get_events_for_date(profile: str, date: str) -> list:
    """Retourne les événements d'un profil pour une date donnée."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT timestamp, type, domain, message FROM events
            WHERE profile=? AND timestamp LIKE ?
            ORDER BY timestamp ASC
        """, (profile, f"{date}%")).fetchall()
    return [dict(r) for r in rows]


def set_device_override(ip: str, duration_minutes: int, taken_by: str = "parent"):
    now = datetime.now()
    expires_at = (now + timedelta(minutes=duration_minutes)).isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO device_overrides (ip, expires_at, taken_by, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
                expires_at=excluded.expires_at,
                taken_by=excluded.taken_by,
                created_at=excluded.created_at
        """, (ip, expires_at, taken_by, now.isoformat()))


def get_device_override(ip: str) -> dict | None:
    now = datetime.now().isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT ip, expires_at, taken_by, created_at FROM device_overrides WHERE ip=? AND expires_at > ?",
            (ip, now)
        ).fetchone()
    return dict(row) if row else None


def get_expired_override_ips() -> list[str]:
    now = datetime.now().isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT ip FROM device_overrides WHERE expires_at <= ?", (now,)
        ).fetchall()
    return [r["ip"] for r in rows]


def clear_device_override(ip: str):
    with get_db() as conn:
        conn.execute("DELETE FROM device_overrides WHERE ip=?", (ip,))


def get_override_for_date(profile: str, date: str) -> dict | None:
    """Retourne l'override de planning pour un profil/date, ou None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT mode, reason FROM schedule_overrides WHERE profile=? AND date=?",
            (profile, date)
        ).fetchone()
    return dict(row) if row else None


def get_usage_range(profile: str, days: int) -> list[dict]:
    """Usage DNS par domaine pour les N derniers jours."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, domain, queries FROM daily_usage
            WHERE profile=? AND date >= ?
            ORDER BY date ASC, queries DESC
        """, (profile, cutoff)).fetchall()
    return [dict(r) for r in rows]


def get_events_range(profile: str, days: int) -> list[dict]:
    """Événements pour les N derniers jours."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT timestamp, type, domain, message FROM events
            WHERE profile=? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (profile, cutoff)).fetchall()
    return [dict(r) for r in rows]


def init_domains_table(conn=None):
    """Ajoute la table domains si absente — appelé par init_db()."""
    sql = """
        CREATE TABLE IF NOT EXISTS domains (
            domain              TEXT PRIMARY KEY,
            category            TEXT DEFAULT 'unknown',
            hits_total          INTEGER DEFAULT 0,
            blocked_work        INTEGER DEFAULT 0,
            blocked_permissive  INTEGER DEFAULT 0,
            first_seen          TEXT,
            last_seen           TEXT,
            last_mode           TEXT,
            categorized_at      TEXT,
            categorized_by      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_domains_category
            ON domains(category);
    """
    if conn:
        conn.executescript(sql)
    else:
        with sqlite3.connect(DB_PATH) as c:
            c.executescript(sql)
            c.commit()
