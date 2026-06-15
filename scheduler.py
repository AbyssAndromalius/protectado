# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
"""
scheduler.py — Calcule le slot d'accès actuel par profil et jour.
Le planning est lu depuis config.json (profiles[key]["schedule"]).
"""

import json
from datetime import datetime, time, timedelta
from paths import CONFIG_PATH

MODE_LABELS = {
    "blocked":    "🔴 Bloqué",
    "work":       "📚 Travail",
    "permissive": "🟢 Libre",
}

_DAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Extensions de slot en mémoire (non persistées) — (minutes, date_iso)
_slot_extensions: dict[str, tuple[int, str]] = {}

# Overrides temporaires de mode — (mode, expires_at)
_temp_overrides: dict[str, tuple[str, datetime]] = {}


def set_temp_override(profile: str, mode: str, minutes: int) -> None:
    _temp_overrides[profile] = (mode, datetime.now() + timedelta(minutes=minutes))


def clear_temp_override(profile: str) -> None:
    _temp_overrides.pop(profile, None)


def get_temp_override(profile: str) -> str | None:
    """Retourne le mode temporaire actif, ou None si absent/expiré."""
    entry = _temp_overrides.get(profile)
    if entry is None:
        return None
    mode, expires_at = entry
    if datetime.now() >= expires_at:
        _temp_overrides.pop(profile, None)
        return None
    return mode


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _parse_time(s: str) -> time:
    return time.fromisoformat(s)


def get_current_slot(profile: str, now: datetime = None) -> dict:
    if now is None:
        now = datetime.now()

    try:
        config = _load_config()
        profile_data = config.get("profiles", {}).get(profile, {})
    except Exception:
        profile_data = {}

    is_weekend = now.weekday() >= 5
    day_key  = _DAY_KEYS[now.weekday()]
    schedule = profile_data.get("schedule", {})
    schedule_list = schedule.get(day_key, [])
    # Rétrocompatibilité avec l'ancien format weekday/weekend
    if not schedule_list:
        legacy = "weekend" if is_weekend else "weekday"
        schedule_list = schedule.get(legacy, [])
    current_time = now.time()
    ext_raw = _slot_extensions.get(profile, (0, ""))
    extra_min = ext_raw[0] if ext_raw[1] == now.date().isoformat() else 0

    for slot in schedule_list:
        start = _parse_time(slot["start"])
        end   = _parse_time(slot["end"])
        if start <= current_time <= end:
            # Slot actif — appliquer l'extension uniquement à ce slot
            if extra_min:
                end_dt = datetime.combine(now.date(), end) + timedelta(minutes=extra_min)
                end = end_dt.time()
            return {
                "mode":                slot["mode"],
                "profile":             profile,
                "slot_start":          slot["start"],
                "slot_end":            end.strftime("%H:%M"),
                "next_change_minutes": _time_until(now, end),
                "day":                 day_key,
            }
        if extra_min and start <= current_time:
            end_dt = datetime.combine(now.date(), end) + timedelta(minutes=extra_min)
            if current_time <= end_dt.time():
                ext_end = end_dt.time()
                return {
                    "mode":                slot["mode"],
                    "profile":             profile,
                    "slot_start":          slot["start"],
                    "slot_end":            ext_end.strftime("%H:%M"),
                    "next_change_minutes": _time_until(now, ext_end),
                    "day":                 day_key,
                }

    return {
        "mode":                "blocked",
        "profile":             profile,
        "slot_start":          "00:00",
        "slot_end":            "23:59",
        "next_change_minutes": 0,
        "day":                 day_key,
    }


def extend_current_slot(profile: str, minutes: int) -> bool:
    today = datetime.now().date().isoformat()
    current_minutes, current_date = _slot_extensions.get(profile, (0, today))
    accumulated = current_minutes if current_date == today else 0
    _slot_extensions[profile] = (accumulated + minutes, today)
    return True


def get_slot_at(profile: str, dt: datetime) -> dict:
    temp_mode = get_temp_override(profile)
    if temp_mode:
        return {
            "mode":            temp_mode,
            "slot_start":      "00:00",
            "slot_end":        "23:59",
            "override":        True,
            "override_reason": "override_temporaire",
        }
    import database as db
    date_str = dt.strftime("%Y-%m-%d")
    override = db.get_override_for_date(profile, date_str)
    if override and override["mode"] != "normal":
        raw_mode = override["mode"]
        mode = "permissive" if raw_mode == "free" else raw_mode
        return {
            "mode":           mode,
            "slot_start":     "00:00",
            "slot_end":       "23:59",
            "override":       True,
            "override_reason": override.get("reason", ""),
        }
    slot = get_current_slot(profile, now=dt)
    slot["override"] = False
    return slot


def _time_until(now: datetime, target: time) -> int:
    target_dt = now.replace(
        hour=target.hour, minute=target.minute, second=0, microsecond=0
    )
    if target_dt <= now:
        return 0
    return int((target_dt - now).total_seconds() / 60)
