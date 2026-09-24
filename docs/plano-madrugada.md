# Plano — ViraClipe autônomo (GitHub Actions, 21:30 BRT)

**Status:** migrado do S20 FE para Actions em 24/09/2026. Compute 100% no
runner; S20/LG aposentados como compute. Banco persiste via Actions cache
(`viraclipe-db-*`) para dedup/denylist entre dias.
**Decisão base:** o único host sempre ligado (LG K22) é fraco demais para o
pipeline; o Debian com XFCE no S20 FE (SD865) é o host de execução.
O LG fica só com o bot leve (`/status /fila /remover`) + log do pack.

## Modelo de operação

- **Janela de processamento:** 03h-05h no S20 FE, aparelho carregando.
  `python3 -m factory.run_diaria` roda via `cronie` + `crond` dentro do
  Debian (ou no Termux por baixo), com Termux:Boot para sobreviver a reboot.
- **Postagem:** o Buffer agenda sozinho para 9h/12h/15h/18h/21h BRT em conta
  separada do CaçaOfertas. Processar de madrugada não conflita com nada.
- **LG:** só `bot/main.py` em polling + recebe o pack logado no Telegram.
- **Sessão das 21h:** vira monitoramento, não execução — confere
  `buffer.json` do dia e o `/fila` no Telegram.

## Pré-requisitos no S20 FE

1. Debian acessível sem interação (proot-distro/Termux ou UserLAnd persistente).
2. `cronie` + `crond` ativos; Termux:Boot instalado (ou equivalente).
3. `ffmpeg`, `yt-dlp`, `ffprobe` + `pip install -r requirements.txt`.
4. `.env` com chaves (Telegram, Gemini, Twitch, YouTube, Buffer conta 2).
5. Aparelho carregando de madrugada; otimização de bateria desativada
   para Termux/Debian.
6. `assets/fonts/` com Poppins/Archivo (senão o render cai no fallback
   sem título queimado).

## Trava e segurança

- flock do `run_diaria` impede dupla execução (cron + manual).
- Guarda de disco livre antes de cada download (a implementar).
- `raw/` apagado após o pack mesmo em falha (parcialmente implementado).
- Denylist permanente + QC bloqueante como proteção do modo auto-total.
- `factory/cron_diario.sh` atual marca 08h BRT — ajustar para a janela
  03h-05h na implantação.

## Roteiro de implantação

1. Rodada manual validada numa sessão (~21h): 1 VOD curta de ponta a ponta.
2. Ativar 2-3 streamers da whitelist após conferir permissão.
3. Conectar os 3 canais na 2ª conta Buffer + teste de 1 post.
4. Configurar cron 03h no S20 FE + 3 madrugadas de observação via
   `tools/viraclipe_status.py` e log `data/logs/cron-*.log`.
5. Só então considerar aumentar `MAX_VODS_DIA` / `DAILY_CAP`.

## Perguntas em aberto

- Debian via proot-distro/Termux ou UserLAnd? (define onde mora o crond)
- S20 FE dorme carregando de madrugada? (define se 03h é viável)
- Cron dentro do proot sobrevive ao Doze sem Termux:Boot?
