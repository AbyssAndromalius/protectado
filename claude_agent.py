# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
"""
claude_agent.py — IA à la demande uniquement.

Appelé seulement pour :
  1. Analyser des patterns inhabituels (escalade depuis monitor.py)
  2. Répondre au chat parent (dashboard) — avec outils d'action
  3. Rapport quotidien (1 appel/jour)

Coût : quelques centimes/jour maximum.
"""

import json
import os
import threading
from datetime import datetime
from openai import OpenAI
from paths import CONFIG_PATH

import database as db
from monitor import notify_monitor, KEEPALIVE_MAX_HITS

ACTION_QUEUE_DIR = "/tmp/fw-queue"

_LANG_PROMPTS = {
    "fr": {
        "intro": "Tu es Protectado, assistant de supervision réseau familial.",
        "role":  "Tu analyses l'activité internet de {kids}.",
        "style": "Sois factuel, concis et bienveillant. Réponds toujours en français.",
        "constraint": "Ne génère pas d'alertes répétitives — concentre-toi sur ce qui est vraiment inhabituel.",
        "kids_sep": " et ",
        "kids_default": "les enfants",
        "age_suffix": "ans",
    },
    "en": {
        "intro": "You are Protectado, a family network monitoring assistant.",
        "role":  "You analyse the internet activity of {kids}.",
        "style": "Be factual, concise and caring. Always respond in English.",
        "constraint": "Do not generate repetitive alerts — focus on what is truly unusual.",
        "kids_sep": " and ",
        "kids_default": "the children",
        "age_suffix": "y.o.",
    },
    "es": {
        "intro": "Eres Protectado, un asistente de supervisión de red familiar.",
        "role":  "Analizas la actividad en internet de {kids}.",
        "style": "Sé factual, conciso y amable. Responde siempre en español.",
        "constraint": "No generes alertas repetitivas — concéntrate en lo que es realmente inusual.",
        "kids_sep": " y ",
        "kids_default": "los niños",
        "age_suffix": "años",
    },
    "pt": {
        "intro": "Você é Protectado, um assistente de monitorização de rede familiar.",
        "role":  "Você analisa a atividade na internet de {kids}.",
        "style": "Seja factual, conciso e cuidadoso. Responda sempre em português.",
        "constraint": "Não gere alertas repetitivos — concentre-se no que é realmente incomum.",
        "kids_sep": " e ",
        "kids_default": "as crianças",
        "age_suffix": "anos",
    },
}


def _build_system_prompt() -> str:
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        lang = config.get("language", "fr")
        p = _LANG_PROMPTS.get(lang, _LANG_PROMPTS["fr"])
        kids = [
            f"{pr['name']} ({pr['age']} {p['age_suffix']})" if pr.get("age") else pr["name"]
            for pr in config.get("profiles", {}).values()
            if pr.get("mode") != "monitoring" and pr.get("name")
        ]
        kids_str = p["kids_sep"].join(kids) if kids else p["kids_default"]
    except Exception:
        p = _LANG_PROMPTS["fr"]
        kids_str = p["kids_default"]
    return "\n".join([
        p["intro"],
        p["role"].format(kids=kids_str),
        p["style"],
        p["constraint"],
    ])

PARENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "block_device_now",
            "description": "Coupe immédiatement l'accès internet d'un profil",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string"},
                    "reason": {"type": "string"}
                },
                "required": ["profile", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "allow_domain_temporarily",
            "description": "Autorise temporairement un domaine bloqué pour un profil pendant N minutes",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "profile": {"type": "string"},
                    "minutes": {"type": "integer"}
                },
                "required": ["domain", "profile", "minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extend_access",
            "description": "Étend l'accès du profil de N minutes supplémentaires ce soir",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string"},
                    "minutes": {"type": "integer"}
                },
                "required": ["profile", "minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "override_day",
            "description": (
                "Override le planning pour une date précise. "
                "Modes : free=accès libre toute la journée, "
                "work=mode travail (divertissement/social bloqués, éducatif autorisé), "
                "blocked=tout bloqué toute la journée, "
                "normal=planning habituel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string"},
                    "date": {"type": "string", "description": "Format YYYY-MM-DD"},
                    "mode": {"type": "string", "enum": ["free", "work", "blocked", "normal"]},
                    "reason": {"type": "string"}
                },
                "required": ["profile", "date", "mode"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_domain_category",
            "description": "Modifie la catégorie d'un domaine (education/work/entertainment/social/adult/other)",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "category": {"type": "string"}
                },
                "required": ["domain", "category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_blacklist",
            "description": "Ajoute définitivement un domaine à la blacklist work ou permissive",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "list": {"type": "string", "enum": ["work", "permissive", "both"]}
                },
                "required": ["domain", "list"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_history",
            "description": (
                "Analyse l'activité DNS passée d'un profil sur une date donnée. "
                "Retourne les domaines accédés heure par heure, le mode Pi-hole actif "
                "à chaque instant, et si le domaine aurait dû être bloqué. "
                "Utilise cet outil pour expliquer pourquoi un domaine était accessible "
                "ou bloqué à un moment précis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string"},
                    "date": {"type": "string", "description": "Format YYYY-MM-DD"},
                    "domain": {
                        "type": "string",
                        "description": "Optionnel — filtre sur un domaine racine (ex: youtube.com)"
                    }
                },
                "required": ["profile", "date"]
            }
        }
    }
]


def _get_client(config: dict) -> tuple:
    client = OpenAI(
        api_key=config["openrouter"]["api_key"],
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "http://localhost:8080",
            "X-Title": "Protectado"
        }
    )
    model = config["openrouter"]["model"]
    return client, model


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _queue_action(action: str, args: dict):
    os.makedirs(ACTION_QUEUE_DIR, mode=0o700, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    path = os.path.join(ACTION_QUEUE_DIR, f"action-{ts}.json")
    with open(path, "w") as f:
        json.dump({"action": action, "args": args,
                   "queued_at": datetime.now().isoformat()}, f)


def _sync_pihole_blacklists(config: dict):
    """Pousse immédiatement les blacklists work et permissive vers Pi-hole."""
    from pihole_api import PiHoleAPI
    from domain_classifier import get_active_blacklist
    api = PiHoleAPI(config["pihole"]["host"], config["pihole"]["password"])
    for mode in ["work", "permissive"]:
        blacklist = get_active_blacklist(mode)
        for profile_name, profile in config.get("profiles", {}).items():
            if profile.get("mode") == "monitoring":
                continue
            group_id = api.get_group_id(f"{profile_name}-{mode}")
            if group_id is not None:
                api._sync_blacklist(group_id, mode, blacklist)


def _execute_parent_tool(name: str, args: dict, config: dict) -> str:
    """Exécute un outil parent et retourne un message de confirmation en français."""

    if name == "block_device_now":
        profile = args["profile"]
        reason  = args["reason"]
        devices = config["profiles"].get(profile, {}).get("devices", [])
        if not devices:
            return f"Aucun appareil configuré pour le profil {profile}."
        ips = [d["ip"] for d in devices]
        # Blocage via Pi-hole : bascule vers le groupe bloqué (wildcard DNS .*)
        # Le Pi n'est pas un routeur — iptables FORWARD n'aurait aucun effet.
        _queue_action("apply_pihole_mode", {
            "profile": profile,
            "mode": "blocked",
            "device_ips": ips,
            "blacklist": []
        })
        db.log_event(profile, "block_device", "", f"Blocage manuel : {reason}")
        notify_monitor()
        return f"Accès internet coupé pour {profile} ({', '.join(ips)})."

    if name == "allow_domain_temporarily":
        domain  = args["domain"]
        profile = args["profile"]
        minutes = args["minutes"]
        try:
            from pihole_api import PiHoleAPI
            from scheduler import get_slot_at
            pihole = PiHoleAPI(config["pihole"]["host"], config["pihole"]["password"])

            # Retirer uniquement du groupe actif du profil (pas globalement)
            slot = get_slot_at(profile, datetime.now())
            current_mode = slot["mode"]
            if current_mode in ("work", "permissive"):
                group_name = f"{profile}-{current_mode}"
                group_id = pihole.get_group_id(group_name)
                if group_id is not None:
                    pihole.remove_domain_from_group(domain, group_id)
            # En mode blocked, le déblocage d'un domaine n'aurait aucun effet (wildcard .*),
            # donc on ne fait rien.

            def re_block():
                try:
                    cfg = _load_config()
                    _sync_pihole_blacklists(cfg)
                    db.log_event(profile, "info", domain,
                                 "Autorisation temporaire expirée — domaine rebloqué")
                except Exception as e:
                    print(f"[Agent] Erreur re-blocage {domain} : {e}")

            threading.Timer(minutes * 60, re_block).start()
            db.log_event(profile, "info", domain,
                         f"Domaine autorisé temporairement pour {minutes}min")
            return f"{domain} débloqué pour {minutes} minutes. Il sera rebloqué automatiquement."
        except Exception as e:
            return f"Erreur lors du déblocage de {domain} : {e}"

    if name == "extend_access":
        profile = args["profile"]
        minutes = args["minutes"]
        from scheduler import extend_current_slot
        ok = extend_current_slot(profile, minutes)
        if ok:
            db.log_event(profile, "info", "", f"Accès prolongé de {minutes} minutes")
            return f"Accès de {profile} prolongé de {minutes} minutes ce soir."
        return f"Impossible de prolonger l'accès pour {profile} — aucun slot actif en ce moment."

    if name == "override_day":
        profile = args["profile"]
        date    = args["date"]
        mode    = args["mode"]
        reason  = args.get("reason", "")
        with db.get_db() as conn:
            conn.execute("""
                INSERT INTO schedule_overrides (profile, date, mode, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(profile, date) DO UPDATE SET
                    mode=excluded.mode, reason=excluded.reason,
                    created_at=excluded.created_at
            """, (profile, date, mode, reason, datetime.now().isoformat()))
        mode_label = {"free": "libre", "blocked": "bloqué", "normal": "normal"}.get(mode, mode)
        db.log_event(profile, "info", "",
                     f"Override planning {date} : mode {mode}" + (f" — {reason}" if reason else ""))
        notify_monitor()
        return f"Planning de {profile} le {date} : mode {mode_label}."

    if name == "update_domain_category":
        domain   = args["domain"]
        category = args["category"]
        import domain_classifier as dc
        dc.update_domain(domain, category=category, by="parent")
        _sync_pihole_blacklists(config)
        notify_monitor()
        return f"{domain} recatégorisé en « {category} »."

    if name == "add_to_blacklist":
        domain    = args["domain"]
        list_name = args["list"]
        import domain_classifier as dc
        if list_name in ("work", "both"):
            dc.update_domain(domain, blocked_work=1, by="parent")
        if list_name in ("permissive", "both"):
            dc.update_domain(domain, blocked_permissive=1, by="parent")
        all_d = dc.get_all_domains()
        if not any(d["domain"] == domain for d in all_d):
            print(f"[Agent] ERREUR : {domain} non trouvé en DB après insertion")
            return f"Erreur : impossible d'ajouter {domain} à la blacklist."
        _sync_pihole_blacklists(config)
        labels = {"work": "travail", "permissive": "permissif", "both": "travail + permissif"}
        notify_monitor()
        return f"{domain} ajouté à la blacklist {labels.get(list_name, list_name)}."

    if name == "query_history":
        profile = args["profile"]
        date    = args["date"]
        domain  = args.get("domain")

        from scheduler import get_slot_at
        from domain_classifier import get_active_blacklist
        from collections import defaultdict

        hits = db.get_dns_hits(profile, date, domain)
        events = db.get_events_for_date(profile, date)
        override = db.get_override_for_date(profile, date)

        # Planning théorique du jour
        sample_dt = datetime.fromisoformat(f"{date}T12:00:00")
        is_weekend = sample_dt.weekday() >= 5
        day_type = "weekend" if is_weekend else "weekday"
        profile_data = config.get("profiles", {}).get(profile, {})
        schedule_raw = profile_data.get("schedule", {}).get(day_type, [])
        schedule = [
            {"slot_start": s["start"], "slot_end": s["end"], "mode": s["mode"]}
            for s in schedule_raw
        ]

        # Agréger les hits par domaine + fenêtre de 5 min (même granularité que le monitor)
        domain_windows: dict = defaultdict(lambda: defaultdict(int))
        for hit in hits:
            ts  = datetime.fromisoformat(hit["timestamp"])
            dom = hit["domain"]
            bucket_min = (ts.minute // 5) * 5
            bucket = ts.strftime(f"%H:{bucket_min:02d}")
            domain_windows[dom][bucket] += 1

        # Classifier chaque fenêtre : keepalive (bruit de fond) vs activity (usage humain)
        # Keepalive = ≤ KEEPALIVE_MAX_HITS hits sur la fenêtre de 5 min
        domain_summary = []
        for dom, windows in sorted(domain_windows.items(),
                                   key=lambda x: -sum(x[1].values())):
            activity = []
            keepalive_count = 0

            for bucket, count in sorted(windows.items()):
                bucket_dt = datetime.fromisoformat(f"{date}T{bucket}:00")
                slot      = get_slot_at(profile, bucket_dt)
                mode      = slot["mode"]
                blacklist = set(get_active_blacklist(mode))
                blocked   = dom in blacklist

                if count <= KEEPALIVE_MAX_HITS:
                    keepalive_count += 1
                else:
                    activity.append({
                        "window": bucket,
                        "hits": count,
                        "mode": mode,
                        "should_be_blocked": blocked,
                    })

            domain_summary.append({
                "domain": dom,
                "activity_windows": activity,
                "keepalive_windows": keepalive_count,
                "is_background_only": len(activity) == 0,
            })

        result = {
            "profile": profile,
            "date": date,
            "day_type": day_type,
            "override": override,
            "schedule": schedule,
            "domains": domain_summary,
            "events": [
                {
                    "time": e["timestamp"][11:16],
                    "type": e["type"],
                    "domain": e["domain"],
                    "message": e["message"],
                }
                for e in events
            ],
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    return f"Outil inconnu : {name}"


def analyze_unusual_patterns(events: list) -> str:
    """
    Appelé par monitor.py quand des patterns inhabituels s'accumulent.
    Coût : 1 appel par déclenchement.
    """
    config = _load_config()
    client, model = _get_client(config)

    prompt = (
        f"Patterns réseau inhabituels détectés :\n"
        f"{json.dumps(events, indent=2, ensure_ascii=False)}\n\n"
        f"Analyse brièvement (3-4 phrases max) et indique si une action parentale est nécessaire."
    )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=300,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": prompt}
            ]
        )
        analysis = response.choices[0].message.content

        for event in events:
            db.log_event(
                event.get("profile", "global"),
                "info",
                event.get("domain", ""),
                analysis[:200]
            )

        print(f"[Claude] Analyse pattern : {analysis[:100]}...")
        return analysis

    except Exception as e:
        print(f"[Claude] Erreur analyse : {e}")
        return ""


def chat(user_message: str) -> str:
    """
    Chat parent ↔ agent avec outils d'action.
    Appelé uniquement sur action du parent.
    """
    config = _load_config()
    client, model = _get_client(config)

    recent_events = db.get_recent_events(limit=20)
    usage_summary = {}
    for pname in config["profiles"]:
        usage_summary[pname] = db.get_time_spent_today(pname)

    context = {
        "heure": datetime.now().strftime("%H:%M"),
        "usage_aujourd_hui": usage_summary,
        "evenements_recents": recent_events[:10]
    }

    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": (
            f"Contexte :\n{json.dumps(context, indent=2, ensure_ascii=False)}\n\n"
            f"Question : {user_message}"
        )}
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=500,
            tools=PARENT_TOOLS,
            messages=messages
        )

        msg    = response.choices[0].message
        reason = response.choices[0].finish_reason

        if reason == "tool_calls" and msg.tool_calls:
            # Exécuter les outils demandés par Claude
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in msg.tool_calls
                ]
            })

            for tc in msg.tool_calls:
                args   = json.loads(tc.function.arguments)
                result = _execute_parent_tool(tc.function.name, args, config)
                print(f"[Agent] Outil {tc.function.name} → {result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                })

            # Second appel pour formuler la réponse finale
            final = client.chat.completions.create(
                model=model,
                max_tokens=500,
                messages=messages
            )
            return final.choices[0].message.content

        return msg.content

    except Exception as e:
        return f"Erreur : {e}"


def daily_report() -> str:
    """
    Rapport quotidien — 1 appel/jour, planifié à 23h.
    """
    config = _load_config()
    client, model = _get_client(config)

    usage_summary = {}
    for pname in config["profiles"]:
        time_spent = db.get_time_spent_today(pname)
        events     = db.get_events_for_profile(pname, limit=50)
        usage_summary[pname] = {
            "temps_par_domaine": time_spent,
            "nb_alertes":  len([e for e in events if e["type"] in ("warning", "alert")]),
            "nb_blocages": len([e for e in events if e["type"] == "block_device"])
        }

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": (
                    f"Génère un rapport quotidien concis pour les parents.\n"
                    f"Données du jour :\n"
                    f"{json.dumps(usage_summary, indent=2, ensure_ascii=False)}"
                )}
            ]
        )
        report = response.choices[0].message.content

        # Résumé court pour le dashboard (5-6 points max)
        summary_response = client.chat.completions.create(
            model=model,
            max_tokens=200,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": (
                    f"Résume ce rapport en 5 points maximum, en bullet points courts "
                    f"(une ligne chacun). Garde uniquement ce qui est utile à un parent.\n\n"
                    f"{report}"
                )}
            ]
        )
        summary = summary_response.choices[0].message.content
        db.log_event("global", "info", "", f"Rapport quotidien : {summary}")
        return report

    except Exception as e:
        return f"Erreur rapport : {e}"
