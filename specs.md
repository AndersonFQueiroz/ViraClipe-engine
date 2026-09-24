# Especificação técnica — ViraClipe (Fase 1 pós-live)

## 1. Componentes

```text
Discovery (whitelist) --> Ingest yt-dlp (720p VOD) --> Signals (chat+audio)
                                                            |
                                                     top candidatos
                                                            v
                                              Score Gemini Flash (1 call)
                                               viral_score+título+tags
                                                            |
                                                     score_final>=75 ?
                                                      sim / não descarta
                                                            v
                                              Cutter ffmpeg + Render PIL
                                               720x1280 h264/aac faststart
                                                            v
                                              Pack legendas (por rede)
                                                            v
                                                     QC bloqueante
                                                            v
                                              state.db (dedup + agenda)
                                                            v
                                    upload_public --> post_buffer --> Buffer
                                     (Catbox)        (IG/TT/YT slots BRT)
                                                            |
                                                     Telegram log + Kwai zip
```

Processos separados que compartilham `data/`:
- `python3 -m factory.run_diaria` — orquestrador diário (cron + flock).
- bot Telegram leve — só `/status`, `/fila`, `/remover`, log do pack.
- Sem worker ADB (diferente do ReelIfy). Render é local ffmpeg+PIL.

## 2. Discovery

`factory/discovery.py`:
- fonte Fase 1: whitelist SQLite `streamers(handle, plataforma, cortes_liberados, ultimo_vod)`.
- triagem `tools/check_permissao.py`: lê bio/descrição e procura
  `cortes liberados|pode clipar|clipes liberados|pode postar cortes|free clips`.
- Twitch Helix (free, app token) lista últimos VODs; YouTube Data API
  (quota curta: evita `search`, usa `playlistItems` do canal); Kick via
  URL direta + yt-dlp (sem API oficial estável).
- `MIN_VIEWERS` e `MAX_VODS_DIA` via env para não estourar disco/quota.
- saída: `data/<dia>/vods.json`.

## 3. Ingest

`factory/ingest.py`:
- `yt-dlp -f "bv*[height<=720]+ba/b[height<=720]/b" --no-playlist`.
- baixa em `data/<dia>/raw/`, após processar apaga o `.mp4` original.
- chat replay baixado com `chat-downloader` (Twitch/YouTube) em `.json`.
- registra em `vods_processados(video_id PK, plataforma, streamer, duracao, baixado_em)`.

## 4. Signals (pré-filtro local)

`factory/signals.py`:
- chat: janela deslizante 30s, `msgs/seg` normalizado 0-100 + bônus emotes.
  `chat_score = 100 * percentil(janela)` na VOD.
- áudio: `ffmpeg -hide_banner -i in.mp4 -af ebur128 -f null -` parseia
  picos `M` (momentary). `audio_score = 100 * percentil(pico)`.
- funde janelas sobrepostas, expande para 25-70s com hook nos 3s,
  ordena por `0.7*chat + 0.3*audio`, mantém top 20-30.
- saída: `data/<dia>/candidatos.json`. Zero calls de API aqui.

## 5. Score Gemini Flash

`factory/score.py` (reuso do padrão `bot/services/gemini_service.py`):
- input: snippet 40-70s extraído com `-ss/-t` (não a VOD inteira).
- 1 call Flash com áudio ou transcrição + prompt fixo PT-BR retorna JSON:
  `{"viral_score":0-100,"motivo":"","titulo":"","descricao":"","hashtags":[]}`.
- `score_final = 0.5*chat + 0.2*audio + 0.3*viral_score`.
- `GEMINI_MODEL` default `gemini-3.6-flash` (override via env).
  Timeout 60s, retry 1x, em 429/quota usa fallback local:
  `viral_score=null`, título template `"Melhor momento de @streamer"`.
- saída: `data/<dia>/scored.json` ordenado, top 5 com `>=75` vão ao corte.

## 6. Corte e render

`factory/cutter.py` + `factory/render.py` (adaptado de ReelIfy):
- `ffmpeg -ss <ini> -t <dur> -i vod.mp4` + crop vertical:
  `crop=ih*9/16:ih` centralizado (tracking de rosto fica Fase 2).
- escala `720:1280`, `libx264 -preset veryfast -crf 23`, `aac 128k`,
  `+faststart`.
- legendas: transcribe do snippet (mesmo texto do score) → PNGs PIL
  sobrepostos, fonte `assets/fonts/*`, `safe_text()` sem emoji na narração.
- crédito queimado final 2s: `@streamer — VOD original: <url>`.
- nomes: `data/<dia>/corte-<streamer>-<ts>.mp4`.

## 7. Pack por rede

`factory/pack_redes.py` (port do ReelIfy):
- `caption_for(corte, network)`: YouTube pede comentário+link bio,
  Instagram pede direct, TikTok hook primeiro + max 4 tags.
- `titles[key]` max 95 chars com streamer + momento.
- `pack.json`: `captions`, `captions_tt`, `first_comments`, `titles`,
  `videos`, `covers`, `creditos`.
- `_build_kwai_zip()`: mp4 + `-legenda.txt` com links VOD (Kwai manual).

## 8. QC bloqueante

`factory/qc.py` (port do ReelIfy + regras de corte):
- `ffprobe` duração 25-70s (ideal 25-60 aviso), `720x1280`, `h264`+`aac`,
  `>100KB`, faststart (`moov` antes `mdat`), stream áudio presente.
- legenda contém `@streamer` + URL VOD; narração sem emoji/URL, <=60 palavras.
- blocklist `config/blocklist.txt` (toxicidade/NSFW) no título/descrição/transcrito.
- dedup: `(video_id, t_inicio)` não existe em `cortes`/`posts`.
- qualquer falha → exit 1, nada enviado.

## 9. Estado SQLite

`data/viraclipe.db`:
```sql
streamers(handle TEXT, plataforma TEXT, cortes_liberados INT, denylist INT, PRIMARY KEY(handle, plataforma));
vods_processados(video_id TEXT PRIMARY KEY, plataforma TEXT, streamer TEXT, duracao REAL, baixado_em TEXT);
cortes(cut_id TEXT PRIMARY KEY, video_id TEXT, streamer TEXT, t_inicio REAL, duracao REAL,
  chat REAL, audio REAL, viral REAL, score_final REAL, titulo TEXT, status TEXT);
posts(cut_id TEXT, rede TEXT, buffer_id TEXT, agendado_para TEXT, PRIMARY KEY(cut_id, rede));
```
`Queue JSON` não é usada (diferença do ReelIfy) para permitir dedup.

## 10. Upload + post

Reuso direto:
- `factory/upload_public.py`: Catbox → Litterbox → Telegram host, `head_ok()` com `>=100KB`.
- `factory/post_buffer.py`: mesmos `SLOTS_UTC=[(12,0),(15,0),(18,0),(21,0),(0,0)]`,
  `WANT=(instagram,tiktok,youtube)`. Sem `BUFFER_API_KEY` → exit 3.
- `factory/pack_telegram.py`: envia pack + `pack_kwai.zip` ao owner para conferência/log.

## 11. Configuração e execução

Env principais: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_CHAT_ID`,
`GEMINI_API_KEY`, `GEMINI_MODEL`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`,
`YOUTUBE_API_KEY`, `BUFFER_API_KEY`, `SCORE_THRESHOLD=75`, `DAILY_CAP=5`,
`MIN_VIEWERS`, `DB_PATH`, `FACTORY_DATA`.

```bash
pip install -r requirements.txt
cp .env.example .env
python3 -m factory.run_diaria [--date AAAA-MM-DD]
python3 -m tools.viraclipe_status
pytest -q
```

Cron diário 08h BRT roda `run_diaria`; Buffer agenda 9/12/15/18/21 BRT.
`.env`, `*.db`, `data/<dia>/raw/*`, mídias nunca commitados.
