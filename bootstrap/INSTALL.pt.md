[🇬🇧 English](INSTALL.md) | [🇫🇷 Français](INSTALL.fr.md) | [🇪🇸 Español](INSTALL.es.md) | [🇵🇹 Português](INSTALL.pt.md)

# Protectado — Guia de instalação

Este guia cobre a instalação completa do Protectado em casa de uma nova família, desde o cartão SD em branco até ao painel operativo.

---

## Instalação em Linux existente (NAS, PC antigo...)

Se já tem uma máquina Linux na rede familiar — um NAS, mini-PC ou PC antigo com Ubuntu — o bootstrap funciona diretamente nela.

**Requisitos:**
- Debian / Ubuntu (o script usa `apt`)
- A máquina deve estar na **mesma rede local** que os dispositivos dos filhos
- Pi-hole v6 já instalado, **ou** não instalado (o bootstrap instala-o)
- Python 3.10 mínimo (`python3 --version`)
- systemd ativo

> **VPS / servidor remoto: não compatível.** O Pi-hole deve ver o tráfego DNS local. Um servidor cloud não pode desempenhar este papel sem VPN.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

Se o Pi-hole já estiver instalado e configurado, o bootstrap deteta-o e deixa-o intacto — instala apenas o Protectado por cima. Se o Pi-hole estiver ausente, instala-o.

Continuar a partir do **Passo 4** (configuração via assistente).

---

## Instalação em Raspberry Pi (via nominal)

---

## O que preparar ANTES de ir a casa da família

### Hardware

| Artigo | Notas |
|--------|-------|
| Raspberry Pi | Pi 3B+, Pi 4 ou Pi 5 recomendado (Ethernet integrado). Pi 2W funciona por WiFi. |
| Cartão SD | 16 GB mínimo, classe 10 |
| Alimentação | USB-C (Pi 4/5) ou micro-USB (Pi 2W/3) |
| Cabo Ethernet | Opcional mas recomendado — liga o Pi diretamente ao router |

### Contas / chaves a criar antecipadamente

**Chave API OpenRouter** (indispensável — a IA não funcionará sem ela)
1. Criar uma conta em [openrouter.ai](https://openrouter.ai)
2. Adicionar crédito (alguns euros chegam para vários meses)
3. Gerar uma chave API → copiar a chave (começa por `sk-or-`)

---

## Passo 1 — Preparar o cartão SD (no seu PC)

1. Descarregar **Raspberry Pi Imager**: [raspberrypi.com/software](https://www.raspberrypi.com/software/)
2. Inserir o cartão SD no PC
3. No Raspberry Pi Imager:
   - **Dispositivo** → escolher o modelo de Pi
   - **Sistema operativo** → `Raspberry Pi OS Lite (64-bit)`
   - **Armazenamento** → o seu cartão SD
4. Clicar em **⚙️ Editar definições** (antes de gravar!)

Nas definições avançadas, configurar:

```
✅ Nome do host      → protectado
✅ Ativar SSH        → Usar palavra-passe
   Nome de utilizador → pi
   Palavra-passe     → [escolher uma palavra-passe SSH]
✅ Configurar WiFi   → [SSID e palavra-passe do lar]
   País WiFi         → [o seu país]
```

> **Se usar cabo Ethernet**: pode deixar o WiFi sem configurar.

5. Gravar o cartão → inserir no Pi

---

## Passo 2 — Primeiro arranque

1. Ligar o cabo Ethernet **ou** deixar o WiFi ligar automaticamente
2. Ligar a alimentação
3. Aguardar ~60 segundos (o Pi arranca e entra na rede)

**Encontrar o endereço IP do Pi:**

```bash
# Opção A — a partir do seu PC na mesma rede
ping protectado.local

# Opção B — interface de administração do router (normalmente 192.168.1.1)
```

---

## Passo 3 — Ligação SSH e instalação

```bash
ssh pi@protectado.local
```

Uma vez ligado, executar a instalação com um único comando:

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

A instalação demora **5 a 10 minutos**. Instala automaticamente:
- Pi-hole (filtragem DNS)
- Protectado (agente IA + painel)
- Atualizações automáticas

No final, o script mostra:

```
╔══════════════════════════════════════════════════╗
║       Protectado instalado com sucesso!         ║
╚══════════════════════════════════════════════════╝

  Painel  →  http://192.168.x.x:8080

  ┌─ Informações de configuração ───────────────────
  │  PIHOLE_PASSWORD :  xxxxxxxxxxxxxxxx
  └──────────────────────────────────────────────────
```

**Anotar a palavra-passe do Pi-hole** — será pedida no assistente.

---

## Passo 4 — Configuração via o assistente

A partir de qualquer dispositivo na rede, abrir:

```
http://protectado.local:8080
```

O assistente inicia automaticamente (6 passos):

| Passo | O que introduzir |
|-------|-----------------|
| 1 | Boas-vindas — clicar Começar |
| 2 | Rede — verificada automaticamente |
| 3 | Pi-hole — `http://localhost` + palavra-passe do passo 3 |
| 4 | OpenRouter — colar a chave API `sk-or-...` |
| 5 | Painel — escolher uma palavra-passe para os pais |
| 6 | Perfis — nome e idade de cada filho |

---

## Passo 5 — Atribuir dispositivos a perfis

No painel → separador **Dispositivos**:

1. Clicar **Analisar rede**
2. Para cada dispositivo detetado: selecionar o perfil
3. Clicar **Atribuir**

---

## Passo 6 — Configurar franjas horárias

No painel → separador **Perfis**:

1. Clicar **Editar** num perfil
2. Adicionar franjas horárias para Semana e Fim de semana
3. Modos disponíveis: `blocked`, `work`, `permissive`
4. Clicar **Guardar** → **⚙️ Reconfigurar Pi-hole**

---

## Cópia de segurança e restauro

No painel → separador **Gestão** → cartão **Cópia de segurança e restauro**.

---

## Resolução de problemas

```bash
sudo systemctl status protectado-agent
sudo journalctl -u protectado-agent -n 30
pihole status
sudo bash /opt/protectado/update.sh
```

---

## Atualizações automáticas

O Protectado atualiza-se sozinho todas as noites às 3h a partir do ramo `release`.
O Pi-hole atualiza-se todos os domingos às 4h.
Os patches de segurança do SO instalam-se automaticamente via `unattended-upgrades`.

---

## Atualizar uma instalação existente

O script bootstrap deteta automaticamente uma instalação existente e passa para o modo de atualização em vez de reinstalar.

```bash
curl -sSL https://code.barbed.fr/abyss/protectado/raw/branch/release/bootstrap/bootstrap.sh | sudo bash
```

O que a atualização faz:
1. Guarda `config.json` e `protectado.db` numa pasta com data/hora em `/opt/`
2. Descarrega o último código do ramo `release`
3. Restaura `config.json` (os seus perfis e configuração são preservados)
4. Executa as migrações da base de dados (`database.init_db()`)
5. Reinicia os serviços

Se o agente não arrancar após a atualização, o script reverte automaticamente para a cópia de segurança.
