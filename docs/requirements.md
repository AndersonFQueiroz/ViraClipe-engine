# Requisitos do ViraClipe

**Status:** planejamento — Fase 1 pós-live
**Runtime:** Python 3.10+
**Persistência:** SQLite (`data/viraclipe.db`) + arquivos em `data/`
**Infra alvo:** celular LG antigo no Termux (sem GPU) + APIs gratuitas
**Operação:** 100% automática, sem aprovação humana

## Objetivo

Baixar VODs pós-live de streamers com cortes liberados, detectar trechos
realmente aproveitáveis com sinais locais + LLM free, cortar em vertical
9:16 legendado e postar automaticamente 5x/dia no canal de cortes
ViraClipe (YouTube Shorts + TikTok + Instagram Reels via Buffer, Kwai via
pack manual).

## Requisitos funcionais

### RF01 — Discovery com whitelist amigável

O sistema deve manter `streamers` com `cortes_liberados=true/false`.
Fase 1 opera apenas com whitelist de 10-15 streamers que liberam cortes
(bio com "cortes liberados / pode clipar / clipes liberados", clips
ativados no painel, descrição YouTube permitindo repost com crédito,
Discord com canal de cortes).
Script de triagem lê bio/descrição e sugere o flag, curadoria manual
confirma. Aberto/em alta fica para Fase 3, após validação do QC.
Denylist é permanente: pedido de remoção nunca mais corta o autor.

### RF02 — Ingest pós-live (VOD)

Baixar apenas VOD finalizada via `yt-dlp` em 720p max para caber no
Termux. Baixar, processar e apagar o original. Realtime fica para Fase 2
e não faz parte do MVP. Deve registrar `video_id`, plataforma
(twitch/youtube/kick), streamer, duração e data em `vods_processados`.

### RF03 — Sinais locais custo zero (pré-filtro)

Sem gastar API, gerar 20-30 candidatos/dia por VOD com:
- velocidade de chat (msgs/seg + densidade de emotes) via chat replay;
- energia de áudio via `ffmpeg ebur128` (grito, risada, hype).
Candidatos têm `t_inicio/t_fim` de 25-70s com hook nos 3s iniciais.
Nenhum ML local pesado no LG.

### RF04 — Scoring 2º estágio via Gemini Flash (free)

Apenas os top candidatos vão ao Gemini Flash (free tier AI Studio):
1 call = transcrição do snippet + `viral_score 0-100` + título PT-BR +
descrição + hashtags. Nada de transcrever live de 2h.
`score_final = 0.5*chat + 0.2*audio + 0.3*llm` (sem chat: `0.4*audio + 0.6*llm`).
Publica se `>= SCORE_THRESHOLD` (default 75). Se quota falhar,
fallback usa só score local e título template, sem travar o dia.

### RF05 — Corte e render vertical

Corte `ffmpeg` + crop 9:16 + legenda queimada (PIL, sem libass, padrão
ReelIfy). Saída fixa: 720x1280, h264, aac, faststart (`moov` antes de
`mdat`), 25-60s ideal. Sempre creditar `@streamer + link VOD original`.

### RF06 — Pack de legendas por rede

Reuso do padrão `pack_redes.py`: legenda + 1º comentário + título por
rede (YouTube/TikTok/Instagram com CTAs distintos, TikTok com menos
tags). Kwai segue em `pack_kwai.zip` manual.

### RF07 — QC automático bloqueante (substitui aprovação humana)

Como não há revisão, o QC bloqueia envio se falhar em qualquer item:
duração, resolução, codecs, faststart, tamanho mínimo, áudio presente,
blocklist de toxicidade/NSFW, link do VOD presente na legenda,
deduplicação por `video_id+t_inicio`. `qc` com falha = nada postado.

### RF08 — Estado, dedup e agenda 5/dia

SQLite com `vods_processados`, `cortes`, `posts`, `streamers_denylist`.
`DAILY_CAP=5`. Slots fixos BRT 9h/12h/15h/18h/21h
(`SLOTS_UTC=12/15/18/21/00`, igual ReelIfy). Orquestrador com flock
anti-dupla-execução, checkpoint reaproveita vídeo válido sem rebuild.

### RF09 — Postagem automática

Reuso `upload_public.py` (Catbox → Litterbox → Telegram host) para URL
pública + `post_buffer.py` (Buffer API) para IG+TikTok+YouTube agendados
nos slots. Sem `BUFFER_API_KEY` o sistema gera o pack e sai com exit 3
(sem erro). Telegram recebe log + pack Kwai, não pede aprovação.

### RF10 — Operação e takedown

Telegram é só monitor: `/status`, `/fila`, `/remover <cut_id>` (apaga
registro, adiciona streamer à denylist se pedido do autor, orienta
remover post no Buffer). Sem `/aprovar`. Todo corte guarda prova de
origem para remoção rápida.

## Requisitos não funcionais

- Tudo free: sem serviço pago. Pesados só via API free, nunca GPU local.
- Funciona em Termux/Debian sem interface gráfica.
- Segredos só em `.env`, nunca no git. Fila/banco/mídias reais nunca commitados.
- Toda rede, Gemini, yt-dlp e ffmpeg com timeout, retry e logging contextual.
- `SCORE_THRESHOLD`, `DAILY_CAP`, `MIN_VIEWERS`, `POLL_INTERVAL` via env.
- `pytest -q` e `git diff --check` verdes antes de commit.

## Critérios de aceite

1. VOD whitelist de 720p é baixada, processada e apagada sem lotar disco.
2. Pré-filtro local gera candidatos sem nenhuma call de API.
3. Com Gemini ok, 1 call por candidato gera score + título + hashtags.
4. Com Gemini fora/quota estourada, o dia segue em modo degradado local.
5. Score <75 nunca é postado; QC reprovado nunca é postado.
6. 5 cortes/dia saem nos slots BRT via Buffer; Kwai sai em zip.
7. Corte já postado (`video_id+t_inicio`) nunca duplica.
8. `/remover` adiciona à denylist e o streamer sai da whitelist.
9. `pytest -q` passa no Termux sem credenciais reais.
