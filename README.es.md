[🇬🇧 English](README.md) | [🇫🇷 Français](README.fr.md) | [🇪🇸 Español](README.es.md) | [🇵🇹 Português](README.pt.md)

# Protectado

Control parental de red familiar — horarios de acceso, bloqueos automáticos y un asistente IA al que los padres consultan en lenguaje natural.

---

## Cómo funciona

```
WiFi (router)
    ↓ todo el tráfico DNS pasa por →
Pi-hole  (instalado y configurado por el bootstrap)
    ↓ logs + API →
Protectado  (panel :8080 + supervisión automática)
    ↓ bloqueo DNS →
grupos Pi-hole por perfil y modo

Cada noche a las 23h:
  informe diario generado via OpenRouter
```

**Sin intervención de los padres**, Protectado aplica automáticamente el horario configurado: cortar el acceso de noche, pasar a modo trabajo después del colegio, reabrir por la noche.

**Bajo demanda**, el padre escribe en el chat del panel en lenguaje natural — la IA interpreta y actúa.

---

## Instalación

El bootstrap se encarga de todo: Pi-hole, Python, sandbox, servicios systemd.

```bash
# Clonar y ejecutar el bootstrap
git clone https://code.barbed.fr/abyss/protectado.git /opt/protectado
cd /opt/protectado
bash bootstrap/bootstrap.sh
```

El script instala Pi-hole, fija la contraseña automáticamente, configura el sandbox y arranca los servicios. Al final muestra la URL del panel.

---

## Primer acceso

Al primer acceso (`http://IP_PI:8080`), se abre un asistente de configuración:

1. **Red** — detectada automáticamente (gateway, subred)
2. **Pi-hole** — host y contraseña (definidos por el bootstrap)
3. **OpenRouter** — clave API para el asistente IA (`sk-or-...`)
4. **Perfiles** — uno por hijo: nombre, edad, hora de despertar y de acostarse

El horario base se genera automáticamente a partir de las horas introducidas. Se puede ajustar después desde el panel.

---

## Uso diario

### Panel de control

`http://IP_PI:8080`

- Estado en tiempo real de cada perfil (dispositivos activos, modo actual, siguiente franja)
- Historial de eventos (bloqueos, alertas, cambios de modo)
- Catálogo de dominios visitados y su categoría

### Chat para padres

La función principal: escribir lo que se quiere hacer, la IA se ocupa del resto.

| Lo que escribes | Lo que hace |
|---|---|
| "Corta internet a Alicia, tiene que dormir" | Bloquea inmediatamente todos sus dispositivos |
| "Autoriza YouTube a Alicia durante 30 minutos" | Desbloquea youtube.com 30 min y vuelve a bloquear |
| "Dale 45 minutos más a Alicia esta noche" | Retrasa el fin de la franja actual |
| "Mañana Alicia está de vacaciones, modo libre" | Día completo sin restricciones (excepto contenido adulto) |
| "Bloquea todo a Alicia el sábado" | Día completo bloqueado |
| "khanacademy.org es educativo" | Recategoriza el dominio — nunca bloqueado en modo trabajo |
| "Bloquea twitch.tv incluso en modo permisivo" | Lista negra permanente |
| "¿Qué vio Alicia anoche?" | Analiza el historial DNS con contexto horario |

### Modos de acceso

| Modo | Qué es accesible |
|---|---|
| **Bloqueado** | Nada — corte de red completo |
| **Trabajo** | Educación, herramientas escolares. YouTube, redes sociales y contenido adulto bloqueados |
| **Libre** | Todo excepto contenido adulto |

El cambio de modo es automático según el horario. Se puede anular en cualquier momento desde el chat o el panel.

---

## Perfiles

Cada hijo tiene su propio perfil con:
- sus dispositivos (IPs fijas recomendadas)
- su horario semana / fin de semana (franjas `blocked`, `work`, `permissive`)
- anulaciones puntuales (vacaciones, excepción de noche…)

El perfil **monitoring** es especial: observa sin bloquear. Útil para supervisar un dispositivo compartido sin aplicarle reglas.

---

## Modo adulto en dispositivo compartido

Si un hijo usa un dispositivo compartido (TV, tablet familiar), el padre puede cambiar temporalmente el dispositivo a modo adulto sin tocar el perfil del hijo.

Desde el panel: botón **Modo adulto** → contraseña del padre → duración. El dispositivo vuelve automáticamente al perfil del hijo al expirar.

---

## Informe diario

Cada noche a las 23h, Protectado envía automáticamente via OpenRouter:
- la categorización de los nuevos dominios desconocidos
- un resumen del día: tiempo por dominio, alertas, bloqueos

El informe aparece en el panel (sección Eventos) y en los logs.

Para activarlo manualmente:
```bash
cd /opt/protectado && .venv/bin/python daily_report.py
```

---

## Copia de seguridad y restauración

El panel permite guardar y restaurar la configuración con un clic.

- **Copia de seguridad**: botón en el panel → descarga un ZIP (`config.json` + base de datos)
- **Restaurar**: subir el ZIP → configuración recargada en caliente, sin reinicio

---

## Actualización

```bash
cd /opt/protectado
sudo bash update.sh
```

El script obtiene la última versión, migra la base de datos y reinicia los servicios. La configuración (`config.json`) nunca se sobreescribe. Se realiza un rollback automático si el agente no reinicia correctamente.

---

## Resolución de problemas

### Reiniciar los servicios
```bash
sudo systemctl restart protectado-runner protectado-agent
```

### Ver lo que ocurre en directo
```bash
sudo journalctl -fu protectado-agent   # panel + supervisión
sudo journalctl -fu protectado-runner  # bloqueos Pi-hole
```

### Estado de los servicios
```bash
sudo systemctl status protectado-runner protectado-agent
```

### Reinicializar la base de datos
```bash
sudo systemctl stop protectado-agent protectado-runner
cd /opt/protectado && source .venv/bin/activate
rm protectado.db
python -c "import database; database.init_db(); print('OK')"
sudo systemctl start protectado-runner protectado-agent
```

---

## Referencia técnica

### Arquitectura detallada

```
[sandbox nono — Landlock]
  dashboard.py  (FastAPI :8080 — punto de entrada único)
    ├── monitor.py     → hilo 60s, reglas deterministas sin IA
    └── claude_agent.py→ IA via OpenRouter, solo bajo demanda
    ↓ cola de acciones →
/tmp/fw-queue/
    ↓
action_runner.py (root, fuera del sandbox)
    → API Pi-hole (grupos, listas negras por modo)

[cron 23h — fuera del sandbox]
  daily_report.py → 2 llamadas OpenRouter/día máximo
```

La IA nunca se llama durante la supervisión rutinaria — coste prácticamente nulo.

### Seguridad (sandbox)

El agente corre en un sandbox Landlock. Solo puede acceder a:

| Recurso | Acceso |
|---|---|
| `/opt/protectado` | Lectura + escritura |
| `/var/log/pihole` | Lectura |
| `/etc/pihole` | Lectura |
| `/tmp/fw-queue` | Escritura (cola de acciones al runner) |
| Red | solo `openrouter.ai` |
| Todo lo demás | Bloqueado por el kernel |

### Cambiar el modelo IA
En `config.json`:
```json
"openrouter": {
    "model": "anthropic/claude-sonnet-4-5"
}
```
Alternativas económicas: `mistralai/mistral-7b-instruct`, `meta-llama/llama-3-8b-instruct`

### Estructura de archivos

```
/opt/protectado/
├── config.json               ← Configuración (claves, perfiles, dispositivos)
├── protectado.db             ← Base SQLite (eventos, dominios, uso)
├── dashboard.py              ← Servidor web + supervisión (punto de entrada)
├── monitor.py                ← Hilo de supervisión DNS (60s)
├── claude_agent.py           ← IA bajo demanda via OpenRouter
├── scheduler.py              ← Horario por perfil
├── action_runner.py          ← Ejecutor root fuera del sandbox
├── domain_classifier.py      ← Categorización de dominios DNS
├── daily_report.py           ← Informe diario (cron)
├── protectado-agent.json     ← Perfil sandbox nono
├── install.sh / update.sh    ← Instalación y actualizaciones
└── templates/
    ├── index.html            ← Panel de control
    ├── login.html            ← Inicio de sesión
    └── setup.html            ← Asistente de primer acceso
```
