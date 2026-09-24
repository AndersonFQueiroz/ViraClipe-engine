# Guia para agentes e desenvolvedores — ViraClipe

Este documento descreve o comportamento planejado da Fase 1. O código é a
fonte de verdade quando houver divergência com os docs.

## Visão atual

Pipeline pós-live 100% automático, sem aprovação humana (diferença central
do ReelIfy). Dois estágios de scoring para operar tudo no free + Termux:

1. sinais locais free (chat + áudio) geram candidatos sem API;
2. Gemini Flash free dá `viral_score` + título/tags só no top.

Telegram é só monitor/log + takedown, nunca aprovação.

## Fluxo

1. `run_diaria --date HOJE` adquire flock, lê whitelist `streamers`.
2. `discovery` lista VODs novas → `ingest` baixa 720p + chat replay.
3. `signals` gera `candidatos.json` (top 20-30, 25-70s).
4. `score` chama Gemini 1x por candidato, calcula `score_final`,
   mantém top 5 com `>=75`.
5. `cutter+render` gera `720x1280 h264/aac faststart` com crédito.
6. `pack_redes` gera legendas por rede + zip Kwai.
7. `qc` bloqueia tudo se 1 corte reprovar.
8. `upload_public` + `post_buffer` agenda 9/12/15/18/21 BRT.
9. `pack_telegram` loga no owner. Raw apagado, `state.db` atualizado.

Realtime, tracking de rosto e multi-idioma são Fase 2/3 e não devem entrar
no MVP.

## Arquivos principais (Fase 1)

| Arquivo | Responsabilidade |
|---|---|
| `factory/discovery.py` | VODs novas da whitelist |
| `factory/ingest.py` | yt-dlp 720p + chat replay + `vods_processados` |
| `factory/signals.py` | chat_score + audio_score (ebur128), zero API |
| `factory/score.py` | 1 call Flash por candidato + fallback local |
| `factory/cutter.py` | corte + crop 9:16 + 720x1280 faststart |
| `factory/render.py` | legendas PIL + crédito final (port ReelIfy) |
| `factory/pack_redes.py` | legendas/títulos por rede (port ReelIfy) |
| `factory/qc.py` | portão bloqueante + dedup + blocklist |
| `factory/upload_public.py` | Catbox/Litterbox/Telegram host (port ReelIfy) |
| `factory/post_buffer.py` | agenda Buffer IG/TT/YT (port ReelIfy) |
| `factory/run_diaria.py` | orquestrador com flock + checkpoint |
| `tools/check_permissao.py` | triagem "cortes liberados" na bio |
| `tools/viraclipe_status.py` |dashboard terminal da fila e posts |
| `config/settings.py` | env central + `SLOTS_UTC` + thresholds |

## Whitelist e denylist

- Nunca adicionar streamer sem evidência de `cortes liberados`.
- `denylist=1` é permanente, só sai com decisão manual documentada.
- Todo pack leva `@streamer + URL VOD`. Sem crédito, QC reprova.
- `/remover` sempre honra o autor primeiro, discute depois.

## Regras de QC automático

Preserva o modo auto-total: threshold `>=75`, `DAILY_CAP=5`, sem exceção
manual no código diário. Não baixar threshold para "completar 5" — dia
fraco publica menos, não publica ruim. Blocklist e dedup nunca são
desligados via flag rápida.

## Regras para alterações

- Manter tudo free: não introduzir dependência paga, GPU ou modelo local pesado.
- Manter compatível com Termux: sem Docker, sem libass, sem path absoluto.
- Não perguntar aprovação no Telegram; logar prova de origem sempre.
- Escapar texto dinâmico em legendas Markdown.
- Não comitar `.env`, `*.db`, `data/*/raw/*`, mp4/png do usuário.
- Rodar `pytest -q` e `git diff --check` antes de commit.
- Portes do ReelIfy devem manter `head_ok()`, `check_faststart()` e
  semântica de exit codes (`0 ok, 1 QC falhou, 2 lock/duplicado, 3 sem chave Buffer`).
