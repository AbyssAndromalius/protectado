[🇬🇧 English](INSTALL.md) | [🇫🇷 Français](INSTALL.fr.md) | [🇪🇸 Español](INSTALL.es.md) | [🇵🇹 Português](INSTALL.pt.md)

# Protectado — Guide d'installation

Ce guide couvre l'installation complète de Protectado chez une nouvelle famille,
depuis la carte SD vierge jusqu'au dashboard opérationnel.

---

## Installation sur Linux existant (NAS, vieux PC...)

Si tu as déjà une machine Linux sur le réseau de la famille — un NAS, un mini-PC, un vieux PC sous Ubuntu — le bootstrap fonctionne directement dessus.

**Prérequis :**
- Debian / Ubuntu (le script utilise `apt`)
- La machine doit être sur le **même réseau local** que les appareils des enfants
- Pi-hole v6 déjà installé, **ou** pas encore installé (le bootstrap l'installe)
- Python 3.10 minimum (`python3 --version`)
- systemd actif

> **VPS / serveur distant : non compatible.** Pi-hole doit voir le trafic DNS local. Un serveur cloud ne peut pas jouer ce rôle sans VPN.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

Si Pi-hole est déjà installé et configuré, le bootstrap le détecte et le laisse intact — il installe uniquement Protectado par-dessus. Si Pi-hole est absent, il l'installe.

Reprendre ensuite à l'**Étape 4** ci-dessous (configuration via le wizard).

---

## Installation sur Raspberry Pi (voie nominale)

---

## Ce qu'il faut préparer AVANT d'aller chez la famille

### Matériel

| Article | Notes |
|---------|-------|
| Raspberry Pi | Pi 3B+, Pi 4 ou Pi 5 recommandé (Ethernet intégré). Pi 2W fonctionne en WiFi. |
| Carte SD | 16 Go minimum, classe 10 |
| Alimentation | USB-C (Pi 4/5) ou micro-USB (Pi 2W/3) |
| Câble Ethernet | Optionnel mais recommandé — branche le Pi directement sur la box |

### Comptes / clés à créer à l'avance

**Clé API OpenRouter** (indispensable — l'IA ne fonctionnera pas sans elle)
1. Créer un compte sur [openrouter.ai](https://openrouter.ai)
2. Ajouter du crédit (quelques euros suffisent pour plusieurs mois)
3. Générer une clé API → copier la clé (commence par `sk-or-`)

---

## Étape 1 — Préparer la carte SD (sur ton PC)

1. Télécharger **Raspberry Pi Imager** : [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Insérer la carte SD dans ton PC
3. Dans Raspberry Pi Imager :
   - **Appareil** → choisir ton modèle de Pi
   - **Système d'exploitation** → `Raspberry Pi OS Lite (64-bit)`
   - **Stockage** → ta carte SD
4. Cliquer sur **⚙️ Modifier les réglages** (avant de flasher !)

Dans les réglages avancés, configurer :

```
✅ Nom d'hôte        → protectado
✅ Activer SSH        → Utiliser un mot de passe
   Nom d'utilisateur  → pi
   Mot de passe       → [choisir un mot de passe SSH]
✅ Configurer le WiFi → [SSID et mot de passe du foyer]
   Pays WiFi          → FR
```

> **Si tu utilises un câble Ethernet** : tu peux laisser le WiFi non configuré.
> Le Pi obtiendra son IP automatiquement via le câble.

5. Flasher la carte → insérer dans le Pi

---

## Étape 2 — Premier démarrage

1. Brancher le câble Ethernet **ou** laisser le WiFi se connecter automatiquement
2. Brancher l'alimentation
3. Attendre ~60 secondes (le Pi démarre et rejoint le réseau)

**Trouver l'adresse IP du Pi :**

```bash
# Option A — depuis ton PC sur le même réseau
ping protectado.local

# Option B — interface admin de la box (souvent 192.168.1.1)
# Chercher "protectado" ou "raspberrypi" dans la liste des appareils connectés
```

---

## Étape 3 — Connexion SSH et installation

```bash
ssh pi@protectado.local
# (ou ssh pi@192.168.x.x avec l'IP trouvée)
```

Une fois connecté, lancer l'installation en une seule commande :

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

L'installation prend **5 à 10 minutes**. Elle installe automatiquement :
- Pi-hole (filtrage DNS)
- Protectado (agent IA + dashboard)
- Les mises à jour automatiques

À la fin, le script affiche :

```
╔══════════════════════════════════════════════════╗
║          Protectado installé avec succès !      ║
╚══════════════════════════════════════════════════╝

  Dashboard  →  http://192.168.x.x:8080

  ┌─ Informations de configuration ─────────────────
  │  PIHOLE_PASSWORD :  xxxxxxxxxxxxxxxx
  └──────────────────────────────────────────────────
```

**Noter le mot de passe Pi-hole** — il sera demandé dans le wizard.

---

## Étape 4 — Configuration via le wizard

Depuis n'importe quel appareil du réseau, ouvrir :

```
http://protectado.local:8080
```

Le wizard démarre automatiquement (6 étapes) :

| Étape | Ce qu'il faut renseigner |
|-------|--------------------------|
| 1 | Bienvenue — cliquer Commencer |
| 2 | Réseau — vérifié automatiquement (🔌 Ethernet ou 📶 WiFi) |
| 3 | Pi-hole — `http://localhost` + mot de passe noté à l'étape 3 |
| 4 | OpenRouter — coller la clé API `sk-or-...` |
| 5 | Dashboard — choisir un mot de passe pour les parents |
| 6 | Profils — prénom et âge de chaque enfant |

À la fin, le dashboard est accessible et le monitoring démarre.

---

## Étape 5 — Assigner les appareils aux profils

Dans le dashboard → onglet **Appareils** :

1. Cliquer **Scanner le réseau**
2. Pour chaque appareil détecté : sélectionner le profil dans le menu déroulant
3. Cliquer **Assigner**

> **Astuce** : allumer les téléphones/tablettes des enfants pour qu'ils apparaissent dans le scan.

---

## Étape 6 — Configurer les plages horaires

Dans le dashboard → onglet **Profils** :

1. Cliquer **Modifier** sur un profil
2. Ajouter des plages horaires pour Semaine et Weekend
3. Modes disponibles : `blocked` (tout coupé), `work` (éducatif seulement), `permissive` (accès libre)
4. Cliquer **Enregistrer**
5. Cliquer **⚙️ Reconfigurer Pi-hole** pour appliquer les groupes

---

## Sauvegarde & Restauration

Dans le dashboard → onglet **Gestion** → carte **Sauvegarde & Restauration** :

| Action | Description |
|--------|-------------|
| ⬇️ Télécharger | Génère un fichier ZIP contenant `config.json` (profils, planning, clés API) et la base de données SQLite |
| ⬆️ Restaurer | Importe un ZIP précédemment téléchargé — la configuration est rechargée immédiatement sans redémarrage |

> **Conseil** : faire une sauvegarde avant chaque mise à jour manuelle et après toute modification importante des profils.

---

## Dépannage

**Le Pi n'apparaît pas sur le réseau**
- Attendre 2 minutes supplémentaires
- Vérifier que le SSID/mot de passe WiFi est correct (refaire l'étape 1)
- Essayer avec un câble Ethernet

**Le dashboard ne s'ouvre pas**
```bash
sudo systemctl status protectado-agent
sudo journalctl -u protectado-agent -n 30
```

**Pi-hole non accessible**
```bash
pihole status
sudo systemctl restart pihole-FTL
```

**Mettre à jour manuellement**
```bash
sudo bash /opt/protectado/update.sh
```

---

## Mises à jour automatiques

Protectado se met à jour seul chaque nuit à 3h00 depuis la branche `release`.
Pi-hole se met à jour chaque dimanche à 4h00.
Les patches de sécurité OS s'installent automatiquement via `unattended-upgrades`.

---

## Mettre à jour une installation existante

Le script bootstrap détecte automatiquement une installation existante et passe en mode mise à jour au lieu de réinstaller.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

Ce que la mise à jour effectue :
1. Sauvegarde `config.json` et `protectado.db` dans un répertoire horodaté dans `/opt/`
2. Tire le dernier code depuis la branche `release`
3. Restaure `config.json` (vos profils et configuration sont conservés)
4. Lance les migrations de base de données (`database.init_db()`)
5. Redémarre les services

Si l'agent ne démarre pas après la mise à jour, le script revient automatiquement à la sauvegarde.
