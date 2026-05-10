# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
import io
import ipaddress
import json
import os
import re
import subprocess
import unicodedata
import zipfile
import asyncio
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import database as db
from monitor import ProtectadoMonitor
from scheduler import get_current_slot
import claude_agent

app = FastAPI(title="Protectado")
templates = Jinja2Templates(directory="templates")

monitor: ProtectadoMonitor | None = None

# Sessions : token → expiry datetime (TTL 24h)
_sessions: dict[str, datetime] = {}
SESSION_TTL = timedelta(hours=24)

# Rate-limiting login : ip → liste de timestamps de tentatives
_login_attempts: dict[str, list[float]] = {}
LOGIN_WINDOW_SEC  = 300   # fenêtre 5 minutes
LOGIN_MAX_ATTEMPTS = 10   # max 10 tentatives par fenêtre

SUPPORTED_LANGS = ["fr", "en", "es", "pt"]
_PROFILE_KEY_RE = re.compile(r'^[a-z0-9_]{1,64}$')
_VALID_OVERRIDE_MODES = {"blocked", "work", "permissive", "free", "normal"}
_VALID_MODES = {"blocked", "work", "permissive"}
_translations_cache: dict[str, dict] = {}


def _load_translations(lang: str) -> dict:
    if lang not in SUPPORTED_LANGS:
        lang = "fr"
    if lang not in _translations_cache:
        path = os.path.join(os.path.dirname(__file__), "i18n", f"{lang}.json")
        try:
            with open(path, encoding="utf-8") as f:
                _translations_cache[lang] = json.load(f)
        except FileNotFoundError:
            _translations_cache[lang] = _load_translations("fr")
    return _translations_cache[lang]


def _lang() -> str:
    try:
        lang = _load_config().get("language", "fr")
        return lang if lang in SUPPORTED_LANGS else "fr"
    except Exception:
        return "fr"

def _t(lang: str | None = None) -> dict:
    return _load_translations(lang if lang is not None else _lang())


def _load_config() -> dict:
    with open("config.json") as f:
        return json.load(f)


def _save_config(config: dict):
    tmp = "config.json.tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.replace(tmp, "config.json")
    global monitor
    if monitor:
        monitor.reload_config()


def _check_session(request: Request) -> bool:
    token = request.cookies.get("fw_session")
    if not token or token not in _sessions:
        return False
    if datetime.now() > _sessions[token]:
        del _sessions[token]
        return False
    return True


def _record_login_attempt(ip: str) -> bool:
    """
    Enregistre une tentative de login depuis ip.
    Retourne False si le rate-limit est atteint.
    """
    now = datetime.now().timestamp()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SEC]
    if len(attempts) >= LOGIN_MAX_ATTEMPTS:
        _login_attempts[ip] = attempts
        return False
    attempts.append(now)
    _login_attempts[ip] = attempts
    return True


def _slugify(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return name.strip("_")


def _detect_network() -> dict:
    gateway, subnet, iface = "192.168.1.1", "192.168.1.0/24", ""
    try:
        # Préférer Ethernet si disponible
        for candidate in ("eth0", "eth1", "enp1s0", "enp2s0", "end0"):
            r = subprocess.run(["ip", "link", "show", candidate],
                               capture_output=True, text=True)
            if r.returncode == 0 and "state UP" in r.stdout:
                iface = candidate
                break

        out = subprocess.check_output(["ip", "route"], text=True)
        for line in out.splitlines():
            if line.startswith("default"):
                m = re.search(r"via (\S+)", line)
                if m:
                    gateway = m.group(1)
                if not iface:
                    m2 = re.search(r"dev (\S+)", line)
                    if m2:
                        iface = m2.group(1)
            elif "proto kernel" in line:
                m = re.match(r"(\d+\.\d+\.\d+\.\d+/\d+)", line)
                if m and not m.group(1).startswith("169."):
                    subnet = m.group(1)
    except Exception:
        pass

    conn_type = "Ethernet" if (iface.startswith("eth") or iface.startswith("en")) else "WiFi"
    return {"gateway": gateway, "subnet": subnet, "iface": iface, "conn_type": conn_type}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if path == "/setup" or path.startswith("/api/setup") or path.startswith("/api/i18n"):
        if path == "/setup" and os.path.exists("config.json"):
            return RedirectResponse(url="/", status_code=302)
        return await call_next(request)

    if not os.path.exists("config.json"):
        return RedirectResponse(url="/setup", status_code=302)

    if path == "/login":
        return await call_next(request)
    if not _check_session(request):
        return RedirectResponse(url="/login", status_code=302)
    return await call_next(request)


def get_monitor() -> ProtectadoMonitor:
    global monitor
    if monitor is None:
        monitor = ProtectadoMonitor()
        try:
            monitor.pihole.setup_profiles(monitor.config["profiles"])
        except Exception as e:
            print(f"[Setup] Avertissement Pi-hole setup : {e}")
        monitor.start(interval=60)
    return monitor


# ------------------------------------------------------------------ #
#  Auth                                                               #
# ------------------------------------------------------------------ #

@app.get("/api/i18n/{lang}")
async def get_translations(lang: str):
    if lang not in SUPPORTED_LANGS:
        lang = "fr"
    return JSONResponse(_load_translations(lang))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: int = 0):
    lang = _lang()
    return templates.TemplateResponse(request, "login.html", {"error": error, "t": _load_translations(lang), "lang": lang})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    client_ip = request.client.host if request.client else "unknown"
    if not _record_login_attempt(client_ip):
        return RedirectResponse(url="/login?error=2", status_code=302)
    config = _load_config()
    if secrets.compare_digest(password, config.get("dashboard_password", "")):
        token = secrets.token_urlsafe(32)
        _sessions[token] = datetime.now() + SESSION_TTL
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie("fw_session", token, httponly=True, samesite="strict")
        return response
    return RedirectResponse(url="/login?error=1", status_code=302)


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("fw_session")
    if token:
        _sessions.pop(token, None)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("fw_session")
    return response


# ------------------------------------------------------------------ #
#  Routes                                                             #
# ------------------------------------------------------------------ #

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    lang = _lang()
    return templates.TemplateResponse(request, "index.html", {"t": _load_translations(lang), "lang": lang})


@app.get("/api/status")
async def status():
    m = get_monitor()
    config = m.config
    active_ips = m.scanner.get_active_ips()
    queries = m.pihole.get_recent_queries(minutes=5)
    by_ip = m.pihole.queries_by_client(queries)

    profiles_data = {}
    for pname, profile in config["profiles"].items():
        device_ips = [d["ip"] for d in profile.get("devices", [])]
        dns_queries = []
        for ip in device_ips:
            dns_queries.extend(by_ip.get(ip, []))

        bypass = any(ip in active_ips for ip in device_ips) and \
                 len(dns_queries) == 0 and len(device_ips) > 0

        yt_minutes = (
            db.estimate_session_minutes(pname, "youtube.com") +
            db.estimate_session_minutes(pname, "youtu.be")
        )
        yt_limit = None

        # Override adulte actif sur l'un des appareils du profil ?
        takeover = None
        for ip in device_ips:
            ov = db.get_device_override(ip)
            if ov:
                expires = datetime.fromisoformat(ov["expires_at"])
                mins_left = max(0, int((expires - datetime.now()).total_seconds() / 60))
                takeover = {"active": True, "ip": ip,
                            "expires_at": ov["expires_at"],
                            "minutes_remaining": mins_left}
                break

        profiles_data[pname] = {
            "name": profile["name"],
            "age": profile["age"],
            "active_devices": [ip for ip in device_ips if ip in active_ips],
            "device_ips": device_ips,
            "dns_queries_last_5min": len(dns_queries),
            "bypass_suspected": bypass,
            "youtube_minutes_today": yt_minutes,
            "youtube_limit_minutes": yt_limit,
            "youtube_quota_exceeded": yt_limit and yt_minutes >= yt_limit,
            "is_bedtime": get_current_slot(pname)["mode"] == "blocked",
            "takeover": takeover,
        }

    return JSONResponse({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "profiles": profiles_data
    })


@app.get("/api/report")
async def last_report():
    with db.get_db() as conn:
        row = conn.execute("""
            SELECT * FROM events
            WHERE profile = 'global' AND message LIKE 'Rapport quotidien%'
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
    return JSONResponse(dict(row) if row else {})


@app.get("/api/domains")
async def domains():
    from domain_classifier import get_all_domains
    return JSONResponse(get_all_domains())


@app.get("/api/events")
async def events(limit: int = 50):
    return JSONResponse(db.get_recent_events(limit))


@app.get("/api/usage/{profile}")
async def usage(profile: str):
    return JSONResponse(db.get_time_spent_today(profile))


@app.get("/api/schedule")
async def schedule():
    config = _load_config()
    result = {}
    for pname, profile in config["profiles"].items():
        if profile.get("mode") == "monitoring":
            continue
        result[pname] = {
            "name": profile["name"],
            "current_slot": get_current_slot(pname),
            "rules": profile.get("schedule", {})
        }
    return JSONResponse(result)


@app.get("/api/overrides")
async def overrides():
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT profile, date, mode, reason, created_at FROM schedule_overrides ORDER BY date DESC"
        ).fetchall()
    return JSONResponse([dict(r) for r in rows])


class OverrideCreate(BaseModel):
    profile: str
    date: str
    mode: str
    reason: str = ""


@app.post("/api/overrides")
async def create_override(body: OverrideCreate):
    if body.mode not in _VALID_OVERRIDE_MODES:
        return JSONResponse({"ok": False, "error": "Mode invalide"}, status_code=400)
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO schedule_overrides (profile, date, mode, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile, date) DO UPDATE SET
                mode=excluded.mode, reason=excluded.reason, created_at=excluded.created_at
        """, (body.profile, body.date, body.mode, body.reason, datetime.now().isoformat()))
    db.log_event(body.profile, "info", "",
                 f"Override planning {body.date} : mode {body.mode}"
                 + (f" — {body.reason}" if body.reason else ""))
    get_monitor().notify()
    return JSONResponse({"ok": True})


@app.delete("/api/overrides/{profile}/{date}")
async def delete_override(profile: str, date: str):
    with db.get_db() as conn:
        conn.execute(
            "DELETE FROM schedule_overrides WHERE profile=? AND date=?",
            (profile, date)
        )
    get_monitor().notify()
    return JSONResponse({"ok": True})


class DomainUpdate(BaseModel):
    category: str | None = None
    blocked_work: int | None = None
    blocked_permissive: int | None = None


@app.patch("/api/domains/{domain:path}")
async def update_domain_route(domain: str, body: DomainUpdate):
    from domain_classifier import update_domain as _update
    from claude_agent import _sync_pihole_blacklists
    _update(
        domain,
        category=body.category,
        blocked_work=body.blocked_work,
        blocked_permissive=body.blocked_permissive,
        by="parent"
    )
    try:
        config = _load_config()
        _sync_pihole_blacklists(config)
    except Exception as e:
        print(f"[Dashboard] Erreur sync Pi-hole : {e}")
    get_monitor().notify()
    return JSONResponse({"ok": True})


class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


@app.post("/api/chat")
async def chat(body: ChatMessage):
    reply = claude_agent.chat(body.message)
    return JSONResponse({"reply": reply})


# ------------------------------------------------------------------ #
#  SSE                                                                #
# ------------------------------------------------------------------ #

@app.get("/api/stream")
async def stream(request: Request):
    async def event_generator():
        last_event_id = None

        while True:
            if await request.is_disconnected():
                break
            try:
                status_data = (await status()).body
                yield f"event: status\ndata: {status_data.decode()}\n\n"

                events_list = db.get_recent_events(limit=50)
                if events_list:
                    newest_id = events_list[0]["id"]
                    if last_event_id is None:
                        last_event_id = newest_id
                    elif newest_id != last_event_id:
                        new = [e for e in events_list if e["id"] > last_event_id]
                        if new:
                            yield f"event: new_events\ndata: {json.dumps(new)}\n\n"
                        last_event_id = newest_id

            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            await asyncio.sleep(10)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ------------------------------------------------------------------ #
#  Devices                                                            #
# ------------------------------------------------------------------ #

@app.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request):
    t = _t()
    return templates.TemplateResponse(request, "devices.html", {"t": t})


def _format_last_seen(raw) -> str | None:
    """Normalise un timestamp Pi-hole (epoch int ou ISO string) en ISO string."""
    if not raw:
        return None
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw).isoformat()
        return str(raw)
    except Exception:
        return None


@app.get("/api/devices")
async def list_devices():
    m = get_monitor()
    config = m.config

    # Pi-hole clients : appareils faisant des requêtes DNS via Pi-hole
    pihole_clients: dict[str, dict] = {}
    for c in m.pihole.get_clients():
        ip = c.get("client") or c.get("ip", "")
        if ip:
            pihole_clients[ip] = c

    # ARP scan : tous les appareils actifs sur le réseau
    arp_devices: dict[str, dict] = {d["ip"]: d for d in m.scanner.scan()}

    # Union des deux sources
    all_ips = set(pihole_clients.keys()) | set(arp_devices.keys())

    # Carte inverse ip → profile_key depuis config
    assigned: dict[str, str] = {}
    assigned_mac: dict[str, str] = {}
    for key, profile in config.get("profiles", {}).items():
        for device in profile.get("devices", []):
            assigned[device["ip"]] = key
            assigned_mac[device["ip"]] = device.get("mac", "")

    pihole_list = []
    bypass_list = []

    for ip in sorted(all_ips):
        ph  = pihole_clients.get(ip, {})
        arp = arp_devices.get(ip, {})
        via_pihole = ip in pihole_clients

        hostname = (ph.get("name") or ph.get("hostname") or
                    arp.get("vendor") or "")
        last_seen = _format_last_seen(
            ph.get("last_query") or ph.get("last_seen") or ph.get("lastQuery")
        )
        mac = arp.get("mac") or assigned_mac.get(ip, "")

        entry = {
            "ip":              ip,
            "mac":             mac,
            "hostname":        hostname,
            "via_pihole":      via_pihole,
            "last_seen":       last_seen,
            "assigned_profile": assigned.get(ip),
        }

        if via_pihole:
            pihole_list.append(entry)
        else:
            bypass_list.append(entry)

    profiles_list = [
        {"key": k, "name": v["name"]}
        for k, v in config.get("profiles", {}).items()
    ]
    return JSONResponse({
        "pihole":   pihole_list,
        "bypass":   bypass_list,
        "profiles": profiles_list,
    })


class DeviceAssign(BaseModel):
    ip: str
    mac: str = ""
    profile_key: str | None = None  # None = désassigner


@app.post("/api/devices/assign")
async def assign_device(body: DeviceAssign):
    try:
        ipaddress.ip_address(body.ip)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Adresse IP invalide"}, status_code=400)
    config = _load_config()

    # Retirer l'IP de tous les profils existants
    for profile in config.get("profiles", {}).values():
        profile["devices"] = [
            d for d in profile.get("devices", []) if d["ip"] != body.ip
        ]

    # Assigner au nouveau profil si fourni
    if body.profile_key and body.profile_key in config.get("profiles", {}):
        config["profiles"][body.profile_key].setdefault("devices", []).append(
            {"ip": body.ip, "mac": body.mac}
        )

    _save_config(config)
    m = get_monitor()

    # Appliquer immédiatement dans Pi-hole
    if body.profile_key and body.profile_key in config.get("profiles", {}):
        try:
            from scheduler import get_current_slot
            slot = get_current_slot(body.profile_key)
            m.pihole.assign_client_to_group(body.ip, f"{body.profile_key}-{slot['mode']}")
        except Exception as e:
            print(f"[Dashboard] Avertissement assign Pi-hole : {e}")
    elif not body.profile_key:
        # Désassignation : basculer vers le groupe par défaut Pi-hole (groupe 0)
        try:
            m.pihole.assign_client_to_group(body.ip, "Default")
        except Exception:
            pass

    m.notify()
    return JSONResponse({"ok": True})


# ------------------------------------------------------------------ #
#  Profiles CRUD                                                      #
# ------------------------------------------------------------------ #

@app.get("/api/profiles")
async def list_profiles():
    config = _load_config()
    return JSONResponse(config.get("profiles", {}))


class ProfileUpdate(BaseModel):
    name: str
    age: int | None = None
    schedule: dict = {}


@app.post("/api/profiles/pihole-setup")
async def pihole_setup():
    config = _load_config()
    m = get_monitor()
    try:
        m.pihole.setup_profiles(config.get("profiles", {}))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/profiles/{key}")
async def create_or_update_profile(key: str, body: ProfileUpdate):
    if not _PROFILE_KEY_RE.match(key) or key == "monitoring":
        return JSONResponse({"ok": False, "error": "Clé de profil invalide"}, status_code=400)
    config = _load_config()
    existing = config.setdefault("profiles", {}).get(key, {})
    config["profiles"][key] = {
        "name":     body.name,
        "age":      body.age,
        "devices":  existing.get("devices", []),
        "schedule": body.schedule,
    }
    _save_config(config)
    return JSONResponse({"ok": True})


@app.delete("/api/profiles/{key}")
async def delete_profile(key: str):
    config = _load_config()
    if key == "monitoring":
        return JSONResponse({"ok": False, "error": "Le profil monitoring ne peut pas être supprimé"}, status_code=400)
    config.get("profiles", {}).pop(key, None)
    _save_config(config)
    return JSONResponse({"ok": True})


# ------------------------------------------------------------------ #
#  Takeover — mode adulte sur poste partagé                          #
# ------------------------------------------------------------------ #

class TakeoverBody(BaseModel):
    duration_minutes: int = Field(..., ge=1, le=480)
    password: str


def _make_basic_schedule(wake: str, bed: str) -> dict:
    """Génère un planning blocked/permissive depuis heure de réveil et coucher."""
    day = [
        {"start": "00:00", "end": wake, "mode": "blocked"},
        {"start": wake,    "end": bed,  "mode": "permissive"},
        {"start": bed,     "end": "23:59", "mode": "blocked"},
    ]
    return {"weekday": day, "weekend": day}


def _find_profile_for_ip(config: dict, ip: str) -> str | None:
    for pkey, profile in config.get("profiles", {}).items():
        if any(d["ip"] == ip for d in profile.get("devices", [])):
            return pkey
    return None


@app.post("/api/device/{ip}/takeover")
async def device_takeover(ip: str, body: TakeoverBody, request: Request):
    if not _check_session(request):
        return JSONResponse({"ok": False, "error": "Non authentifié"}, status_code=401)
    config = _load_config()
    if not secrets.compare_digest(body.password, config.get("dashboard_password", "")):
        return JSONResponse({"ok": False, "error": "Mot de passe incorrect"}, status_code=403)
    profile_key = _find_profile_for_ip(config, ip)
    if not profile_key:
        return JSONResponse({"ok": False, "error": "Appareil non trouvé"}, status_code=404)
    db.set_device_override(ip, body.duration_minutes)
    m = get_monitor()
    ok = m.pihole.assign_client_to_group(ip, "adult-override")
    db.log_event(profile_key, "info", ip,
                 f"Mode adulte activé — {body.duration_minutes} min")
    return JSONResponse({"ok": ok})


@app.post("/api/device/{ip}/release")
async def device_release(ip: str, request: Request):
    if not _check_session(request):
        return JSONResponse({"ok": False, "error": "Non authentifié"}, status_code=401)
    config = _load_config()
    profile_key = _find_profile_for_ip(config, ip)
    if not profile_key:
        return JSONResponse({"ok": False, "error": "Appareil non trouvé"}, status_code=404)
    db.clear_device_override(ip)
    m = get_monitor()
    slot = get_current_slot(profile_key)
    ok = m.pihole.assign_client_to_group(ip, f"{profile_key}-{slot['mode']}")
    db.log_event(profile_key, "info", ip, "Mode adulte annulé — retour profil enfant")
    return JSONResponse({"ok": ok})


# ------------------------------------------------------------------ #
#  Backup & Restore                                                   #
# ------------------------------------------------------------------ #

@app.get("/backup")
async def backup(request: Request):
    if not _check_session(request):
        return RedirectResponse("/login")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists("config.json"):
            zf.write("config.json")
        if os.path.exists("protectado.db"):
            zf.write("protectado.db")
    buf.seek(0)
    filename = f"protectado-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/restore")
async def restore(request: Request, file: UploadFile = File(...)):
    if not _check_session(request):
        return JSONResponse({"ok": False, "error": "Non authentifié"}, status_code=401)
    data = await file.read()
    install_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if "config.json" not in names:
                return JSONResponse(
                    {"ok": False, "error": "Archive invalide (config.json manquant)"},
                    status_code=400,
                )
            # Valider le JSON avant d'écraser la config en production
            raw_cfg = zf.read("config.json")
            try:
                json.loads(raw_cfg)
            except json.JSONDecodeError:
                return JSONResponse(
                    {"ok": False, "error": "config.json invalide (JSON malformé)"},
                    status_code=400,
                )
            zf.extract("config.json", install_dir)
            if "protectado.db" in names:
                zf.extract("protectado.db", install_dir)
    except zipfile.BadZipFile:
        return JSONResponse({"ok": False, "error": "Fichier ZIP invalide"}, status_code=400)
    global monitor
    if monitor:
        monitor.reload_config()
    return JSONResponse({"ok": True})


# ------------------------------------------------------------------ #
#  Setup wizard                                                       #
# ------------------------------------------------------------------ #

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    return templates.TemplateResponse(request, "setup.html", {})


@app.get("/api/setup/network")
async def setup_network():
    return JSONResponse(_detect_network())


class TestPiholeBody(BaseModel):
    host: str
    password: str


@app.post("/api/setup/test-pihole")
def setup_test_pihole(body: TestPiholeBody):
    import requests as req
    try:
        r = req.post(
            f"{body.host.rstrip('/')}/api/auth",
            json={"password": body.password},
            timeout=5,
        )
        sid = r.json().get("session", {}).get("sid")
        if sid:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": "Authentification échouée — vérifiez le mot de passe"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


class SetupProfile(BaseModel):
    name: str
    age: str | None = None
    wake: str = "07:00"
    bed: str = "22:00"


class SetupSaveBody(BaseModel):
    gateway: str
    subnet: str
    pihole_host: str
    pihole_password: str
    openrouter_key: str
    openrouter_model: str
    dashboard_password: str
    language: str = "fr"
    profiles: list[SetupProfile]


@app.post("/api/setup/save")
async def setup_save(body: SetupSaveBody):
    if os.path.exists("config.json"):
        return JSONResponse({"ok": False, "error": "Configuration déjà existante"}, status_code=409)

    profiles: dict = {}
    seen: set[str] = set()
    for p in body.profiles:
        name = p.name.strip()
        if not name:
            continue
        key = _slugify(name) or "profil"
        base, n = key, 2
        while key in seen:
            key = f"{base}_{n}"
            n += 1
        seen.add(key)
        age = int(p.age) if p.age and str(p.age).isdigit() else None
        schedule = _make_basic_schedule(p.wake or "07:00", p.bed or "22:00")
        profiles[key] = {"name": name, "age": age, "devices": [], "schedule": schedule}

    profiles["monitoring"] = {
        "name": "Monitoring",
        "age": None,
        "mode": "monitoring",
        "devices": [],
        "comment": "Surveillance passive. Ignoré si devices vide.",
    }

    lang = body.language if body.language in SUPPORTED_LANGS else "fr"
    config = {
        "dashboard_password": body.dashboard_password,
        "language": lang,
        "pihole": {"host": body.pihole_host, "password": body.pihole_password},
        "network": {"gateway": body.gateway, "subnet": body.subnet},
        "openrouter": {"api_key": body.openrouter_key, "model": body.openrouter_model},
        "profiles": profiles,
    }

    with open("config.json", "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return JSONResponse({"ok": True})


# ------------------------------------------------------------------ #
#  Point d'entrée                                                     #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import uvicorn
    try:
        get_monitor()
    except FileNotFoundError:
        print("[Démarrage] config.json absent — wizard de configuration requis")
    uvicorn.run("dashboard:app", host="0.0.0.0", port=8080, reload=False)
