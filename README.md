<div align="center">

# ✂️ ViraClipe

**Da live ao viral — cortes automáticos, todos os dias.**

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://github.com/AndersonFQueiroz/ViraClipe/actions/workflows/ci.yml"><img src="https://github.com/AndersonFQueiroz/ViraClipe/actions/workflows/ci.yml/badge.svg" alt="CI Tests"></a>
  <a href="https://core.telegram.org/bots"><img src="https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white" alt="Telegram Bot"></a>
  <a href="https://aistudio.google.com"><img src="https://img.shields.io/badge/AI%20Engine-Google%20Gemini-4285F4?logo=google&logoColor=white" alt="Google Gemini"></a>
  <a href="#-arquitetura"><img src="https://img.shields.io/badge/Pipeline-Autonomous%205x%2Fday-blueviolet?logo=speedtest&logoColor=white" alt="Pipeline"></a>
</p>

</div>

---

**ViraClipe** baixa VODs pós-live de streamers com cortes liberados, detecta os
trechos realmente aproveitáveis com sinais locais + IA gratuita, corta em
vertical 9:16 legendado e posta **5x por dia, 100% no automático** no canal de
cortes (YouTube Shorts + TikTok + Instagram Reels via Buffer, Kwai via pack manual).

> **Processamento de madrugada, posts o dia todo:** o pipeline roda 03h-05h no
> Debian do S20 FE e agenda os 5 slots (9h/12h/15h/18h/21h BRT) sozinho. O LG
> fica só com o bot leve de monitoramento.

---

## ✨ Funcionalidades

| Recurso | Descrição |
|:---|:---|
| 🔍 **Discovery com whitelist** | Só streamers com cortes liberados; denylist permanente com 1 toque |
| 📥 **Ingest pós-live** | `yt-dlp` em 720p + chat replay; baixa, processa e apaga o original |
| 📊 **Sinais locais custo zero** | Pico de chat (msgs/seg + emotes) + energia de áudio (`ebur128`), sem API |
| 🧠 **Score Gemini Flash (free)** | 1 call por candidato: `viral_score` + título + hashtags; fallback local sem travar |
| ✂️ **Corte vertical** | `ffmpeg` crop 9:16 + 720x1280, h264/aac + faststart, hook + crédito queimados |
| 🏷️ **Pack por rede** | Legenda + 1º comentário + título adaptados (Shorts/Reels/TikTok), zip do Kwai |
| 🛡️ **QC bloqueante** | Reprovou 1 corte, nada é postado (duração, specs, blocklist, dedup, crédito) |
| 📮 **Auto-post Buffer** | Agenda os 5 slots BRT sozinho; sem chave, gera o pack e sai sem erro |
| 🤖 **Bot monitor** | Só `/status`, `/fila` e `/remover` (takedown com denylist automática) |

---

## 🏗️ Arquitetura

```
              ┌─────────────────────────────┐
              │  Lives em alta (Twitch /    │
              │  YouTube / Kick - whitelist)│
              └─────────────┬───────────────┘
                            │ pós-live (VOD)
                            ▼
              ┌─────────────────────────────┐
              │   Discovery + Ingest        │
              │   (yt-dlp 720p + chat)      │
              └─────────────┬───────────────┘
                            │
              ┌─────────────▼───────────────┐
              │   Signals locais (free)     │
              │   chat_velocity + ebur128   │──→ top 20-30 candidatos
              └─────────────┬───────────────┘
                            │
              ┌─────────────▼───────────────┐
              │   Score Gemini Flash (free) │
              │   viral_score + título/tags │──→ top 5 (score ≥ 75)
              └─────────────┬───────────────┘
                            │
              ┌─────────────▼───────────────┐
              │   Cutter + Render (ffmpeg)  │
              │   720x1280 h264/aac         │
              └─────────────┬───────────────┘
                            │
              ┌─────────────▼───────────────┐
              │   Pack + QC bloqueante      │
              └─────────────┬───────────────┘
                            │
              ┌─────────────▼───────────────┐
              │   Buffer (IG/TT/YT) +       │
              │   Telegram log + Kwai zip   │
              └─────────────────────────────┘
```

Fórmula do score: `final = 0.5*chat + 0.2*audio + 0.3*llm` → publica se `≥ 75`.

---

## 📁 Estrutura do Projeto

```
ViraClipe/
├── config/
│   ├── settings.py            # Env central (slots, thresholds, paths)
│   └── blocklist.txt          # Termos que reprovam o corte no QC
├── factory/
│   ├── run_diaria.py          # Orquestrador diário (flock + cron)
│   ├── cron_diario.sh         # Gatilho diário (janela 03h-05h no S20 FE)
│   ├── discovery.py           # VODs novas da whitelist → vods.json
│   ├── ingest.py              # yt-dlp 720p + chat replay → ingest.json
│   ├── signals.py             # chat + áudio → candidatos.json (zero API)
│   ├── score.py               # Gemini Flash → scored.json (top 5)
│   ├── cutter.py              # corte 9:16 → cortes.json
│   ├── render.py              # hook + crédito → finais.json
│   ├── pack_redes.py          # legendas/títulos + pack_kwai.zip
│   ├── qc.py                  # portão bloqueante + dedup
│   ├── db.py                  # SQLite (whitelist, vods, cortes, posts)
│   ├── net.py                 # retry backoff p/ rede
│   ├── upload_public.py       # Catbox/Litterbox/Telegram host
│   ├── post_buffer.py         # agenda Buffer IG/TT/YT (auto-total)
│   └── pack_telegram.py       # log do pack no Telegram do dono
├── bot/
│   └── main.py                # /status, /fila, /remover (só monitor)
├── tools/
│   ├── seed_whitelist.py      # seed + ativação da whitelist
│   ├── check_permissao.py     # triagem "cortes liberados" na bio
│   └── viraclipe_status.py    # dashboard de terminal
├── data/
│   ├── whitelist_seed.csv     # 12 streamers candidatos
│   └── factory/               # dia a dia (vods → buffer.json)
├── docs/                      # requirements, specs, agents, plano-madrugada
├── tests/                     # 20 testes (sem rede, sem ffmpeg real)
├── .env.example               # template (tudo free)
└── requirements.txt
```

---

## 🚀 Instalação & Configuração

### Pré-requisitos

- **Python 3.10+**, **ffmpeg** (`ffprobe` incluso) e **yt-dlp**
- Chaves gratuitas: Gemini (AI Studio), Twitch (app), YouTube Data v3, Buffer (conta separada do CaçaOfertas)

### 1. Clone e instale

```bash
git clone https://github.com/AndersonFQueiroz/ViraClipe.git
cd ViraClipe
pip install -r requirements.txt
```

### 2. Configure as credenciais

```bash
cp .env.example .env
```

| Variável | Origem | Finalidade |
|:---|:---|:---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_OWNER_CHAT_ID` | @BotFather | Log do pack + `/status` `/remover` |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | AI Studio | `viral_score` + títulos (free) |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | dev.twitch.tv | Discovery de VODs |
| `YOUTUBE_API_KEY` | Cloud Console | Discovery de VODs |
| `BUFFER_API_KEY` | publish.buffer.com | Auto-post IG/TT/YT |
| `SCORE_THRESHOLD=75` / `DAILY_CAP=5` | — | Trava de qualidade + volume |

### 3. Ative a whitelist e rode

```bash
python3 -m tools.seed_whitelist --seed
python3 -m tools.check_permissao "bio copiada do canal"
python3 -m tools.seed_whitelist --activate alanzoka twitch
python3 -m factory.run_diaria --date AAAA-MM-DD
python3 -m tools.viraclipe_status
pytest -q
```

---

## 🕒 Operação

| Horário BRT | O quê |
|:---|:---|
| 03h-05h | Pipeline roda sozinho no S20 FE (Debian) |
| 9h / 12h / 15h / 18h / 21h | Buffer publica 1 corte por slot |
| 21h | Você confere `/fila` + `buffer.json` na sessão Debian |

Takedown: `/remover <cut_id> [motivo]` marca o corte como removido e joga o
streamer na denylist permanente (apague o post no painel do Buffer).

---

## 📚 Docs

| Doc | Conteúdo |
|:---|:---|
| `docs/requirements.md` | RF01-RF10 + critérios de aceite |
| `docs/specs.md` | Especificação técnica do pipeline |
| `docs/agents.md` | Guia para agentes/desenvolvedores |
| `docs/plano-madrugada.md` | Operação autônoma no S20 FE |

## Status

🚧 Fase 1 em construção — pipeline pós-live + bot leve prontos, implantação na madrugada pendente.
