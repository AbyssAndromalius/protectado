# Protectado

**Supervision intelligente du réseau familial — automatique, adaptative, bienveillante.**

Protectado est un système de contrôle parental réseau open source conçu pour les 
parents d'adolescents. Il tourne sur un Raspberry Pi branché à votre réseau 
domestique et gère automatiquement l'accès internet de vos enfants — sans que 
vous ayez à surveiller manuellement chaque nouveau site ou application.

---

## Pourquoi Protectado ?

Les adolescents naviguent sur des centaines de domaines par jour. Les outils de 
contrôle parental traditionnels s'appuient sur des listes statiques que les enfants 
contournent en quelques minutes. Les parents n'ont pas le temps de suivre 
l'évolution constante du web.

Protectado règle ce problème différemment : **il apprend, catégorise et bloque 
dynamiquement**, sans intervention manuelle. Chaque nouveau domaine visité est 
analysé automatiquement et classé selon son contenu. Les règles s'appliquent 
en temps réel, s'adaptent aux nouvelles plateformes, et vous informent de ce 
qui se passe — pour que vous puissiez avoir les bonnes conversations avec 
votre enfant plutôt que de courir après les contournements.

---

## Ce que Protectado fait

- **Blocage dynamique** — Les domaines sont catégorisés automatiquement par IA 
  et les règles s'appliquent immédiatement, sans liste à maintenir manuellement
- **Plannings horaires** — Accès restreint la nuit, mode travail pendant les 
  devoirs, mode libre le weekend — configurés une fois, appliqués automatiquement
- **Rapports quotidiens** — Synthèse intelligente en langage naturel de la journée 
  numérique de votre enfant
- **Alertes contextuelles** — Détection des tentatives de contournement DNS, 
  des patterns inhabituels, des contenus préoccupants
- **Agent IA** — Posez des questions en français et obtenez des réponses claires. 
  Donnez des instructions : "bloque TikTok pour Alice", "autorise Signal ce soir"
- **Visibilité complète** — Tableau de bord temps réel par appareil et par enfant

---

## Ce que Protectado n'est pas

Protectado observe les patterns de navigation réseau — pas le contenu des 
messages privés ni les conversations de vos enfants. Il agit au niveau du DNS : 
il sait que votre enfant a visité YouTube, pas ce qu'il y a regardé.

L'objectif n'est pas la surveillance totale mais **un cadre de vie numérique 
sain et prévisible** — des règles claires, appliquées automatiquement, qui 
laissent de la place pour la confiance et le dialogue.

---

## Architecture

Protectado repose sur [Pi-hole](https://pi-hole.net) comme moteur DNS, enrichi 
d'une couche d'intelligence artificielle pour la classification et l'analyse.

### Modèles matériels

| Modèle | Matériel | Capacités |
|--------|----------|-----------|
| **Basic** | Raspberry Pi 2W | Blocage DNS dynamique, rapports IA, plannings |
| **Advanced** | Raspberry Pi 4/5 | + Interruption des sessions actives, blocage VPN |
| **Zealot** | Raspberry Pi 4/5 | + Inspection SSL navigateur web |

### Composants logiciels
```
protectado-client    Ce dépôt — tourne sur votre Raspberry Pi
protectado-server    Serveur central (classification partagée, anonyme)
protectado.com       Site web et documentation (à venir)
```

---

## Installation

Une seule commande depuis votre Raspberry Pi :

```bash
curl -fsSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | bash
```

Un assistant web vous guide ensuite en quelques minutes pour configurer 
vos profils d'enfants, leurs plannings et connecter vos appareils.

> **Prérequis** : Raspberry Pi (2W, 3, 4 ou 5) · Raspberry Pi OS ou Ubuntu 
> · Connexion à votre réseau domestique

---

## Vie privée

Toutes les données restent **sur votre Raspberry Pi**. Protectado ne collecte 
aucune donnée personnelle. Le serveur central (optionnel) ne reçoit que des 
noms de domaines anonymes pour la classification — jamais d'identifiants 
familiaux, d'adresses IP ou d'historique de navigation.

---

## Licence

Protectado est disponible sous deux licences :

- **Usage personnel / open source** : GNU AGPL v3 — voir [LICENSE](LICENSE)
- **Usage commercial** : Licence Commerciale Protectado — 
  voir [LICENSE-COMMERCIAL](LICENSE-COMMERCIAL) · arnaud@barbed.fr

Copyright (C) 2026 Arnaud Ortais

Protectado utilise [Pi-hole](https://pi-hole.net), licencié sous EUPL v1.2.
