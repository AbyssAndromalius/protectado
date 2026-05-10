[🇬🇧 English](README.md) | [🇫🇷 Français](README.fr.md) | [🇪🇸 Español](README.es.md) | [🇵🇹 Português](README.pt.md)

# Protectado

Contrôle parental réseau pour toute la famille — planning horaire, blocages automatiques, et un assistant IA que le parent interroge en langage naturel.

---

## Comment ça marche

```
WiFi (box, routeur)
    ↓ tout le trafic DNS passe par →
Pi-hole  (installé et configuré par le bootstrap)
    ↓ logs + API →
Protectado  (dashboard :8080 + surveillance automatique)
    ↓ blocages DNS →
groupes Pi-hole par profil et par mode

Chaque nuit à 23h :
  rapport quotidien généré via OpenRouter
```

**Sans action parentale**, Protectado applique seul le planning configuré : couper l'accès la nuit, passer en mode travail après l'école, rouvrir en soirée.

**Sur demande**, le parent écrit dans le chat du dashboard en français naturel — l'IA interprète et agit.

---

## Installation

Le bootstrap prend en charge tout : Pi-hole, Python, sandbox, services systemd.

```bash
# Cloner et lancer le bootstrap
git clone https://code.barbed.fr/abyss/protectado.git /opt/protectado
cd /opt/protectado
bash bootstrap/bootstrap.sh
```

Le script installe Pi-hole, fixe le mot de passe automatiquement, configure le sandbox et démarre les services. À la fin, il affiche l'URL du dashboard.

---

## Premier démarrage

Au premier accès (`http://IP_DU_PI:8080`), un assistant de configuration s'ouvre :

1. **Réseau** — détecté automatiquement (gateway, sous-réseau)
2. **Pi-hole** — hôte et mot de passe (définis par le bootstrap)
3. **OpenRouter** — clé API pour l'assistant IA (`sk-or-...`)
4. **Profils** — un par enfant : prénom, âge, heure de réveil et de coucher

Le planning de base est généré automatiquement depuis les heures saisies. Il est ajustable ensuite depuis le dashboard.

---

## Utilisation quotidienne

### Dashboard

`http://IP_DU_PI:8080`

- Statut en temps réel de chaque profil (appareils actifs, mode en cours, plage suivante)
- Historique des événements (blocages, alertes, changements de mode)
- Catalogue des domaines visités et leur catégorie

### Chat parent

La fonctionnalité principale : écrire ce qu'on veut faire, l'IA s'occupe du reste.

| Ce que vous écrivez | Ce que ça fait |
|---|---|
| "Coupe internet à Alice, elle doit dormir" | Bloque immédiatement tous ses appareils |
| "Autorise YouTube pour Alice pendant 30 minutes" | Débloque youtube.com 30 min puis rebloque |
| "Donne 45 minutes de plus à Alice ce soir" | Repousse la fin du créneau actuel |
| "Demain Alice est en vacances, mode libre" | Journée entière sans restriction (sauf adulte) |
| "Bloque tout pour Alice samedi" | Journée entière bloquée |
| "khanacademy.org c'est éducatif" | Recatégorise le domaine — jamais bloqué en mode travail |
| "Bloque twitch.tv même en mode permissif" | Blacklist permanente |
| "Qu'est-ce qu'Alice a regardé hier soir ?" | Analyse l'historique DNS avec le contexte horaire |

### Modes d'accès

| Mode | Ce qui est accessible |
|---|---|
| **Bloqué** | Rien — coupure réseau complète |
| **Travail** | Éducation, outils scolaires. YouTube, réseaux sociaux et contenus adultes bloqués |
| **Libre** | Tout sauf les contenus adultes |

Le passage d'un mode à l'autre est automatique selon le planning. Il peut être surchargé à tout moment depuis le chat ou le dashboard.

---

## Profils

Chaque enfant a son propre profil avec :
- ses appareils (IP fixes recommandées)
- son planning semaine / weekend (créneaux `blocked`, `work`, `permissive`)
- ses overrides ponctuels (vacances, exception du soir…)

Le profil **monitoring** est spécial : il observe sans bloquer. Utile pour surveiller un appareil partagé sans lui appliquer de règles.

---

## Mode adulte sur appareil partagé

Si un enfant utilise un appareil partagé (TV, tablette familiale), le parent peut basculer temporairement l'appareil en mode adulte sans toucher au profil de l'enfant.

Depuis le dashboard : bouton **Mode adulte** → mot de passe parent → durée. L'appareil revient automatiquement dans le profil enfant à l'expiration.

---

## Rapport quotidien

Chaque soir à 23h, Protectado envoie automatiquement via OpenRouter :
- la catégorisation des nouveaux domaines inconnus
- un résumé de la journée : temps passé par domaine, alertes, blocages

Le rapport apparaît dans le dashboard (section Événements) et dans les logs.

Pour le déclencher manuellement :
```bash
cd /opt/protectado && .venv/bin/python daily_report.py
```

---

## Backup & Restore

Le dashboard permet de sauvegarder et restaurer la configuration en un clic.

- **Backup** : bouton dans le dashboard → télécharge un ZIP (`config.json` + base de données)
- **Restore** : uploader le ZIP → configuration rechargée à chaud, sans redémarrage

---

## Mise à jour

```bash
cd /opt/protectado
sudo bash update.sh
```

Le script récupère la dernière version, migre la base de données et redémarre les services. La configuration (`config.json`) n'est jamais écrasée. Un rollback automatique est effectué si l'agent ne redémarre pas correctement.

---

## En cas de problème

### Redémarrer les services
```bash
sudo systemctl restart protectado-runner protectado-agent
```

### Voir ce qui se passe en direct
```bash
sudo journalctl -fu protectado-agent   # dashboard + surveillance
sudo journalctl -fu protectado-runner  # blocages Pi-hole
```

### Statut des services
```bash
sudo systemctl status protectado-runner protectado-agent
```

### Réinitialiser la base de données
```bash
sudo systemctl stop protectado-agent protectado-runner
cd /opt/protectado && source .venv/bin/activate
rm protectado.db
python -c "import database; database.init_db(); print('OK')"
sudo systemctl start protectado-runner protectado-agent
```

---

## Référence technique

### Architecture détaillée

```
[nono sandbox — Landlock]
  dashboard.py  (FastAPI :8080 — point d'entrée unique)
    ├── monitor.py     → thread 60s, règles déterministes sans IA
    └── claude_agent.py→ IA via OpenRouter, sur demande uniquement
    ↓ file d'actions →
/tmp/fw-queue/
    ↓
action_runner.py (root, hors sandbox)
    → Pi-hole API (groupes, blacklists par mode)

[cron 23h — hors sandbox]
  daily_report.py → 2 appels OpenRouter/jour maximum
```

L'IA n'est jamais sollicitée pendant la surveillance courante — coût quasi nul au quotidien.

### Sécurité (sandbox)

L'agent tourne dans un sandbox Landlock. Il ne peut accéder qu'à :

| Ressource | Accès |
|---|---|
| `/opt/protectado` | Lecture + écriture |
| `/var/log/pihole` | Lecture |
| `/etc/pihole` | Lecture |
| `/tmp/fw-queue` | Écriture (file d'actions vers le runner) |
| Réseau | `openrouter.ai` uniquement |
| Tout le reste | Bloqué par le kernel |

### Changer le modèle IA
Dans `config.json` :
```json
"openrouter": {
    "model": "anthropic/claude-sonnet-4-5"
}
```
Alternatives économiques : `mistralai/mistral-7b-instruct`, `meta-llama/llama-3-8b-instruct`

### Structure des fichiers

```
/opt/protectado/
├── config.json               ← Configuration (clés, profils, appareils)
├── protectado.db             ← Base SQLite (événements, domaines, usage)
├── dashboard.py              ← Serveur web + surveillance (point d'entrée)
├── monitor.py                ← Thread de surveillance DNS (60s)
├── claude_agent.py           ← IA à la demande via OpenRouter
├── scheduler.py              ← Planning horaire par profil
├── action_runner.py          ← Exécuteur root hors sandbox
├── domain_classifier.py      ← Catégorisation domaines DNS
├── daily_report.py           ← Rapport quotidien (cron)
├── protectado-agent.json     ← Profil sandbox nono
├── install.sh / update.sh    ← Installation et mises à jour
└── templates/
    ├── index.html            ← Dashboard
    ├── login.html            ← Connexion
    └── setup.html            ← Assistant premier démarrage
```
