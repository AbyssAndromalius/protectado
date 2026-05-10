[🇬🇧 English](INSTALL.md) | [🇫🇷 Français](INSTALL.fr.md) | [🇪🇸 Español](INSTALL.es.md) | [🇵🇹 Português](INSTALL.pt.md)

# Protectado — Guía de instalación

Esta guía cubre la instalación completa de Protectado en casa de una nueva familia, desde la tarjeta SD en blanco hasta el panel operativo.

---

## Instalación en Linux existente (NAS, PC antiguo...)

Si ya tienes una máquina Linux en la red familiar — un NAS, mini-PC o PC antiguo con Ubuntu — el bootstrap funciona directamente en ella.

**Requisitos:**
- Debian / Ubuntu (el script usa `apt`)
- La máquina debe estar en la **misma red local** que los dispositivos de los hijos
- Pi-hole v6 ya instalado, **o** no instalado (el bootstrap lo instala)
- Python 3.10 mínimo (`python3 --version`)
- systemd activo

> **VPS / servidor remoto: no compatible.** Pi-hole debe ver el tráfico DNS local. Un servidor en la nube no puede desempeñar este rol sin VPN.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

Si Pi-hole ya está instalado y configurado, el bootstrap lo detecta y lo deja intacto — solo instala Protectado encima. Si Pi-hole no está, lo instala.

Continuar desde el **Paso 4** (configuración via el asistente).

---

## Instalación en Raspberry Pi (vía nominal)

---

## Qué preparar ANTES de ir a casa de la familia

### Hardware

| Artículo | Notas |
|---------|-------|
| Raspberry Pi | Pi 3B+, Pi 4 o Pi 5 recomendado (Ethernet integrado). Pi 2W funciona por WiFi. |
| Tarjeta SD | 16 GB mínimo, clase 10 |
| Alimentación | USB-C (Pi 4/5) o micro-USB (Pi 2W/3) |
| Cable Ethernet | Opcional pero recomendado — conecta el Pi directamente al router |

### Cuentas / claves a crear de antemano

**Clave API OpenRouter** (imprescindible — la IA no funcionará sin ella)
1. Crear una cuenta en [openrouter.ai](https://openrouter.ai)
2. Añadir crédito (unos pocos euros duran varios meses)
3. Generar una clave API → copiar la clave (empieza por `sk-or-`)

---

## Paso 1 — Preparar la tarjeta SD (en tu PC)

1. Descargar **Raspberry Pi Imager**: [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Insertar la tarjeta SD en tu PC
3. En Raspberry Pi Imager:
   - **Dispositivo** → elegir tu modelo de Pi
   - **Sistema operativo** → `Raspberry Pi OS Lite (64-bit)`
   - **Almacenamiento** → tu tarjeta SD
4. Clicar en **⚙️ Editar ajustes** (¡antes de grabar!)

En los ajustes avanzados, configurar:

```
✅ Nombre de host    → protectado
✅ Activar SSH       → Usar contraseña
   Nombre de usuario → pi
   Contraseña        → [elegir una contraseña SSH]
✅ Configurar WiFi   → [SSID y contraseña del hogar]
   País WiFi         → [tu país]
```

> **Si usas cable Ethernet**: puedes dejar el WiFi sin configurar.

5. Grabar la tarjeta → insertar en el Pi

---

## Paso 2 — Primer arranque

1. Conectar el cable Ethernet **o** dejar que el WiFi se conecte automáticamente
2. Conectar la alimentación
3. Esperar ~60 segundos (el Pi arranca y se une a la red)

**Encontrar la IP del Pi:**

```bash
# Opción A — desde tu PC en la misma red
ping protectado.local

# Opción B — interfaz de administración del router (normalmente 192.168.1.1)
```

---

## Paso 3 — Conexión SSH e instalación

```bash
ssh pi@protectado.local
```

Una vez conectado, ejecutar la instalación con un único comando:

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

La instalación tarda **5 a 10 minutos**. Instala automáticamente:
- Pi-hole (filtrado DNS)
- Protectado (agente IA + panel)
- Actualizaciones automáticas

Al final, el script muestra:

```
╔══════════════════════════════════════════════════╗
║        ¡Protectado instalado con éxito!         ║
╚══════════════════════════════════════════════════╝

  Panel  →  http://192.168.x.x:8080

  ┌─ Información de configuración ──────────────────
  │  PIHOLE_PASSWORD :  xxxxxxxxxxxxxxxx
  └──────────────────────────────────────────────────
```

**Anotar la contraseña de Pi-hole** — la pedirá el asistente.

---

## Paso 4 — Configuración via el asistente

Desde cualquier dispositivo de la red, abrir:

```
http://protectado.local:8080
```

El asistente se inicia automáticamente (6 pasos):

| Paso | Qué introducir |
|------|----------------|
| 1 | Bienvenida — clicar Empezar |
| 2 | Red — verificada automáticamente |
| 3 | Pi-hole — `http://localhost` + contraseña del paso 3 |
| 4 | OpenRouter — pegar la clave API `sk-or-...` |
| 5 | Panel — elegir una contraseña para los padres |
| 6 | Perfiles — nombre y edad de cada hijo |

---

## Paso 5 — Asignar dispositivos a perfiles

En el panel → pestaña **Dispositivos**:

1. Clicar **Escanear red**
2. Para cada dispositivo detectado: seleccionar el perfil
3. Clicar **Asignar**

---

## Paso 6 — Configurar franjas horarias

En el panel → pestaña **Perfiles**:

1. Clicar **Editar** en un perfil
2. Añadir franjas horarias para Semana y Fin de semana
3. Modos disponibles: `blocked`, `work`, `permissive`
4. Clicar **Guardar** → **⚙️ Reconfigurar Pi-hole**

---

## Copia de seguridad y restauración

En el panel → pestaña **Gestión** → tarjeta **Copia de seguridad y restauración**.

---

## Resolución de problemas

```bash
sudo systemctl status protectado-agent
sudo journalctl -u protectado-agent -n 30
pihole status
sudo bash /opt/protectado/update.sh
```

---

## Actualizaciones automáticas

Protectado se actualiza solo cada noche a las 3h desde la rama `release`.
Pi-hole se actualiza cada domingo a las 4h.
Los parches de seguridad del SO se instalan automáticamente via `unattended-upgrades`.

---

## Actualizar una instalación existente

El script bootstrap detecta automáticamente una instalación existente y cambia al modo actualización en lugar de reinstalar.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

Qué hace la actualización:
1. Guarda `config.json` y `protectado.db` en un directorio con marca de tiempo en `/opt/`
2. Descarga el último código desde la rama `release`
3. Restaura `config.json` (tus perfiles y configuración se conservan)
4. Ejecuta las migraciones de la base de datos (`database.init_db()`)
5. Reinicia los servicios

Si el agente no arranca tras la actualización, el script vuelve automáticamente a la copia de seguridad.
