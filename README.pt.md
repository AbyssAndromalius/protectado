[🇬🇧 English](README.md) | [🇫🇷 Français](README.fr.md) | [🇪🇸 Español](README.es.md) | [🇵🇹 Português](README.pt.md)

# Protectado

Controlo parental de rede familiar — horários de acesso, bloqueios automáticos e um assistente IA que os pais consultam em linguagem natural.

---

## Como funciona

```
WiFi (router)
    ↓ todo o tráfego DNS passa por →
Pi-hole  (instalado e configurado pelo bootstrap)
    ↓ logs + API →
Protectado  (painel :8080 + supervisão automática)
    ↓ bloqueio DNS →
grupos Pi-hole por perfil e modo

Todas as noites às 23h:
  relatório diário gerado via OpenRouter
```

**Sem intervenção dos pais**, o Protectado aplica automaticamente o horário configurado: cortar o acesso de noite, passar para modo trabalho após a escola, reabrir à noite.

**Sob pedido**, o pai escreve no chat do painel em linguagem natural — a IA interpreta e age.

---

## Instalação

O bootstrap trata de tudo: Pi-hole, Python, sandbox, serviços systemd.

```bash
# Clonar e executar o bootstrap
git clone https://code.barbed.fr/abyss/protectado.git /opt/protectado
cd /opt/protectado
bash bootstrap/bootstrap.sh
```

O script instala o Pi-hole, define a palavra-passe automaticamente, configura o sandbox e inicia os serviços. No final, mostra o URL do painel.

---

## Primeiro acesso

No primeiro acesso (`http://IP_PI:8080`), abre-se um assistente de configuração:

1. **Rede** — detetada automaticamente (gateway, sub-rede)
2. **Pi-hole** — host e palavra-passe (definidos pelo bootstrap)
3. **OpenRouter** — chave API para o assistente IA (`sk-or-...`)
4. **Perfis** — um por filho: nome, idade, hora de acordar e de deitar

O horário base é gerado automaticamente a partir dos horários introduzidos. Pode ser ajustado depois a partir do painel.

---

## Utilização diária

### Painel de controlo

`http://IP_PI:8080`

- Estado em tempo real de cada perfil (dispositivos ativos, modo atual, próxima franja)
- Histórico de eventos (bloqueios, alertas, mudanças de modo)
- Catálogo de domínios visitados e a sua categoria

### Chat para pais

A funcionalidade principal: escrever o que se quer fazer, a IA trata do resto.

| O que escreve | O que faz |
|---|---|
| "Corta o internet à Alice, ela tem de dormir" | Bloqueia imediatamente todos os seus dispositivos |
| "Autoriza o YouTube à Alice durante 30 minutos" | Desbloqueia youtube.com 30 min e volta a bloquear |
| "Dá mais 45 minutos à Alice esta noite" | Adia o fim da franja atual |
| "Amanhã a Alice está de férias, modo livre" | Dia completo sem restrições (exceto conteúdo adulto) |
| "Bloqueia tudo à Alice no sábado" | Dia completo bloqueado |
| "khanacademy.org é educativo" | Recategoriza o domínio — nunca bloqueado em modo trabalho |
| "Bloqueia twitch.tv mesmo em modo permissivo" | Lista negra permanente |
| "O que é que a Alice viu ontem à noite?" | Analisa o histórico DNS com contexto horário |

### Modos de acesso

| Modo | O que está acessível |
|---|---|
| **Bloqueado** | Nada — corte de rede completo |
| **Trabalho** | Educação, ferramentas escolares. YouTube, redes sociais e conteúdo adulto bloqueados |
| **Livre** | Tudo exceto conteúdo adulto |

A mudança de modo é automática conforme o horário. Pode ser substituída a qualquer momento a partir do chat ou do painel.

---

## Perfis

Cada filho tem o seu próprio perfil com:
- os seus dispositivos (IPs fixos recomendados)
- o seu horário semana / fim de semana (franjas `blocked`, `work`, `permissive`)
- substituições pontuais (férias, exceção de noite…)

O perfil **monitoring** é especial: observa sem bloquear. Útil para supervisionar um dispositivo partilhado sem lhe aplicar regras.

---

## Modo adulto em dispositivo partilhado

Se um filho usa um dispositivo partilhado (TV, tablet familiar), o pai pode mudar temporariamente o dispositivo para modo adulto sem tocar no perfil do filho.

No painel: botão **Modo adulto** → palavra-passe do pai → duração. O dispositivo volta automaticamente ao perfil do filho ao expirar.

---

## Relatório diário

Todas as noites às 23h, o Protectado envia automaticamente via OpenRouter:
- a categorização dos novos domínios desconhecidos
- um resumo do dia: tempo por domínio, alertas, bloqueios

O relatório aparece no painel (secção Eventos) e nos logs.

Para o acionar manualmente:
```bash
cd /opt/protectado && .venv/bin/python daily_report.py
```

---

## Cópia de segurança e restauro

O painel permite guardar e restaurar a configuração com um clique.

- **Cópia de segurança**: botão no painel → descarrega um ZIP (`config.json` + base de dados)
- **Restaurar**: carregar o ZIP → configuração recarregada em tempo real, sem reinício

---

## Atualização

```bash
cd /opt/protectado
sudo bash update.sh
```

O script obtém a versão mais recente, migra a base de dados e reinicia os serviços. A configuração (`config.json`) nunca é sobrescrita. É feito um rollback automático se o agente não reiniciar corretamente.

---

## Resolução de problemas

### Reiniciar os serviços
```bash
sudo systemctl restart protectado-runner protectado-agent
```

### Ver o que acontece em direto
```bash
sudo journalctl -fu protectado-agent   # painel + supervisão
sudo journalctl -fu protectado-runner  # bloqueios Pi-hole
```

### Estado dos serviços
```bash
sudo systemctl status protectado-runner protectado-agent
```

### Reinicializar a base de dados
```bash
sudo systemctl stop protectado-agent protectado-runner
cd /opt/protectado && source .venv/bin/activate
rm protectado.db
python -c "import database; database.init_db(); print('OK')"
sudo systemctl start protectado-runner protectado-agent
```

---

## Referência técnica

### Arquitetura detalhada

```
[sandbox nono — Landlock]
  dashboard.py  (FastAPI :8080 — ponto de entrada único)
    ├── monitor.py     → thread 60s, regras deterministas sem IA
    └── claude_agent.py→ IA via OpenRouter, apenas sob pedido
    ↓ fila de ações →
/tmp/fw-queue/
    ↓
action_runner.py (root, fora do sandbox)
    → API Pi-hole (grupos, listas negras por modo)

[cron 23h — fora do sandbox]
  daily_report.py → 2 chamadas OpenRouter/dia máximo
```

A IA nunca é chamada durante a supervisão de rotina — custo praticamente nulo.

### Segurança (sandbox)

O agente corre num sandbox Landlock. Só pode aceder a:

| Recurso | Acesso |
|---|---|
| `/opt/protectado` | Leitura + escrita |
| `/var/log/pihole` | Leitura |
| `/etc/pihole` | Leitura |
| `/tmp/fw-queue` | Escrita (fila de ações para o runner) |
| Rede | apenas `openrouter.ai` |
| Todo o resto | Bloqueado pelo kernel |

### Mudar o modelo IA
Em `config.json`:
```json
"openrouter": {
    "model": "anthropic/claude-sonnet-4-5"
}
```
Alternativas económicas: `mistralai/mistral-7b-instruct`, `meta-llama/llama-3-8b-instruct`

### Estrutura de ficheiros

```
/opt/protectado/
├── config.json               ← Configuração (chaves, perfis, dispositivos)
├── protectado.db             ← Base SQLite (eventos, domínios, uso)
├── dashboard.py              ← Servidor web + supervisão (ponto de entrada)
├── monitor.py                ← Thread de supervisão DNS (60s)
├── claude_agent.py           ← IA sob pedido via OpenRouter
├── scheduler.py              ← Horário por perfil
├── action_runner.py          ← Executor root fora do sandbox
├── domain_classifier.py      ← Categorização de domínios DNS
├── daily_report.py           ← Relatório diário (cron)
├── protectado-agent.json     ← Perfil sandbox nono
├── install.sh / update.sh    ← Instalação e atualizações
└── templates/
    ├── index.html            ← Painel de controlo
    ├── login.html            ← Início de sessão
    └── setup.html            ← Assistente de primeiro acesso
```
