[🇬🇧 English](INSTALL.md) | [🇫🇷 Français](INSTALL.fr.md) | [🇪🇸 Español](INSTALL.es.md) | [🇵🇹 Português](INSTALL.pt.md)

# Protectado — Installation Guide

This guide covers the complete installation of Protectado at a new family's home, from a blank SD card to an operational dashboard.

---

## Installation on an existing Linux machine (NAS, old PC...)

If you already have a Linux machine on the family network — a NAS, mini-PC, or old PC running Ubuntu — the bootstrap works directly on it.

**Requirements:**
- Debian / Ubuntu (the script uses `apt`)
- The machine must be on the **same local network** as the children's devices
- Pi-hole v6 already installed, **or** not yet installed (the bootstrap installs it)
- Python 3.10 minimum (`python3 --version`)
- systemd active

> **VPS / remote server: not compatible.** Pi-hole must see local DNS traffic. A cloud server cannot play this role without a VPN.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

If Pi-hole is already installed and configured, the bootstrap detects it and leaves it intact — it only installs Protectado on top. If Pi-hole is absent, it installs it.

Continue from **Step 4** below (wizard configuration).

---

## Installation on Raspberry Pi (nominal path)

---

## What to prepare BEFORE going to the family's home

### Hardware

| Item | Notes |
|------|-------|
| Raspberry Pi | Pi 3B+, Pi 4 or Pi 5 recommended (built-in Ethernet). Pi 2W works over WiFi. |
| SD card | 16 GB minimum, class 10 |
| Power supply | USB-C (Pi 4/5) or micro-USB (Pi 2W/3) |
| Ethernet cable | Optional but recommended — plugs the Pi directly into the router |

### Accounts / keys to create in advance

**OpenRouter API key** (essential — AI will not work without it)
1. Create an account at [openrouter.ai](https://openrouter.ai)
2. Add credit (a few euros lasts several months)
3. Generate an API key → copy the key (starts with `sk-or-`)

---

## Step 1 — Prepare the SD card (on your PC)

1. Download **Raspberry Pi Imager**: [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Insert the SD card into your PC
3. In Raspberry Pi Imager:
   - **Device** → choose your Pi model
   - **Operating system** → `Raspberry Pi OS Lite (64-bit)`
   - **Storage** → your SD card
4. Click **⚙️ Edit settings** (before flashing!)

In the advanced settings, configure:

```
✅ Hostname          → protectado
✅ Enable SSH         → Use a password
   Username           → pi
   Password           → [choose an SSH password]
✅ Configure WiFi     → [household SSID and password]
   WiFi country       → [your country]
```

> **If using an Ethernet cable**: you can leave WiFi unconfigured.
> The Pi will get its IP automatically via the cable.

5. Flash the card → insert into the Pi

---

## Step 2 — First boot

1. Plug in the Ethernet cable **or** let WiFi connect automatically
2. Plug in the power supply
3. Wait ~60 seconds (the Pi boots and joins the network)

**Find the Pi's IP address:**

```bash
# Option A — from your PC on the same network
ping protectado.local

# Option B — router admin interface (often 192.168.1.1)
# Look for "protectado" or "raspberrypi" in the connected devices list
```

---

## Step 3 — SSH connection and installation

```bash
ssh pi@protectado.local
# (or ssh pi@192.168.x.x with the IP found above)
```

Once connected, run the installation with a single command:

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

Installation takes **5 to 10 minutes**. It automatically installs:
- Pi-hole (DNS filtering)
- Protectado (AI agent + dashboard)
- Automatic updates

At the end, the script displays:

```
╔══════════════════════════════════════════════════╗
║        Protectado installed successfully!       ║
╚══════════════════════════════════════════════════╝

  Dashboard  →  http://192.168.x.x:8080

  ┌─ Configuration information ──────────────────────
  │  PIHOLE_PASSWORD :  xxxxxxxxxxxxxxxx
  └──────────────────────────────────────────────────
```

**Note the Pi-hole password** — it will be needed in the wizard.

---

## Step 4 — Configuration via the wizard

From any device on the network, open:

```
http://protectado.local:8080
```

The wizard starts automatically (6 steps):

| Step | What to enter |
|------|---------------|
| 1 | Welcome — click Get started |
| 2 | Network — verified automatically (🔌 Ethernet or 📶 WiFi) |
| 3 | Pi-hole — `http://localhost` + password noted in step 3 |
| 4 | OpenRouter — paste the API key `sk-or-...` |
| 5 | Dashboard — choose a parent password |
| 6 | Profiles — name and age of each child |

At the end, the dashboard is accessible and monitoring starts.

---

## Step 5 — Assign devices to profiles

In the dashboard → **Devices** tab:

1. Click **Scan network**
2. For each detected device: select the profile from the dropdown
3. Click **Assign**

> **Tip**: turn on the children's phones/tablets so they appear in the scan.

---

## Step 6 — Configure time slots

In the dashboard → **Profiles** tab:

1. Click **Edit** on a profile
2. Add time slots for Weekday and Weekend
3. Available modes: `blocked` (all cut), `work` (educational only), `permissive` (open access)
4. Click **Save**
5. Click **⚙️ Reconfigure Pi-hole** to apply the groups

---

## Backup & Restore

In the dashboard → **Management** tab → **Backup & Restore** card:

| Action | Description |
|--------|-------------|
| ⬇️ Download | Generates a ZIP containing `config.json` (profiles, schedule, API keys) and the SQLite database |
| ⬆️ Restore | Imports a previously downloaded ZIP — configuration is reloaded immediately without restart |

> **Tip**: back up before each manual update and after any significant profile changes.

---

## Troubleshooting

**Pi not appearing on the network**
- Wait an extra 2 minutes
- Check that the SSID/WiFi password is correct (redo step 1)
- Try with an Ethernet cable

**Dashboard not opening**
```bash
sudo systemctl status protectado-agent
sudo journalctl -u protectado-agent -n 30
```

**Pi-hole not accessible**
```bash
pihole status
sudo systemctl restart pihole-FTL
```

**Manual update**
```bash
sudo bash /opt/protectado/update.sh
```

---

## Automatic updates

Protectado updates itself every night at 3am from the `release` branch.
Pi-hole updates every Sunday at 4am.
OS security patches install automatically via `unattended-upgrades`.

---

## Updating an existing installation

The bootstrap script automatically detects an existing Protectado installation and switches to update mode instead of reinstalling.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

What the update does:
1. Saves `config.json` and `protectado.db` to a timestamped backup in `/opt/`
2. Pulls the latest code from the `release` branch
3. Restores `config.json` (your profiles and configuration are preserved)
4. Runs database migrations (`database.init_db()`)
5. Restarts the services

If the agent fails to start after the update, the script automatically rolls back to the saved backup.
