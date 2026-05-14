#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
#
# Obsolète depuis la correction de sécurité (mai 2026).
# Conservé uniquement pour compatibilité avec les installations antérieures
# dont le cron pointe encore sur ce chemin.
#
# Le script de mise à jour sécurisé est désormais installé dans
# /usr/local/sbin/protectado-update (root:root 755) par bootstrap.sh.

exec /usr/local/sbin/protectado-update "$@"
