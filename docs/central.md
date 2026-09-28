# Central de 1º comentário (CaçaComentarios)

O ViraClipe **não posta primeiro comentário sozinho**. Isso é papel da
central (`AndersonFQueiroz/CacaComentarios`, Next.js + Postgres + worker),
que já tem as contas OAuth conectadas (IG + YT) e os sweepers.

## Regra de ouro

**Texto SEMPRE genérico, uma campanha só.** Ex: *"gostou do corte? comenta
aí o que achou 👇"*. Nunca texto por vídeo — isso exigiria uma campanha
por vídeo e não escala (decisão do dono, 28/09/2026). Tentativa anterior
de fila por-corte foi construída e **revertida** pelos dois lados; não
ressuscitar sem falar com o dono.

A central também **não responde comentários nem DMs** nesse fluxo —
só o 1º comentário (decisão do dono: reply automático em canal assim
ficaria zoado).

## Campanhas ativas (criadas 28/09/2026)

| Rede | Conta | Campanha | Texto |
|---|---|---|---|
| IG | `viraclipe.oficial` | `ViraClipe — 1º comentário` (Automation, matchAnyPost, resto desligado) | genérico 👆 |
| YT | `Vira Clipe` | `ViraClipe — 1º comentário` (YoutubeAutomation, keywords vazias) | genérico 👆 |

Sweepers: IG a cada 5 min (só reels <12h, 1x por post), YT a cada 10 min
(só vídeos <12h, 1x por vídeo). Worker `worker/dm-worker.ts` online na Railway.

## Onde mora e como acessar

- App: `https://cacacomentarios-production.up.railway.app`
- Projeto Railway: `outstanding-energy` (services `CacaComentarios` + `worker`)
- Banco: Neon pooler (`DATABASE_URL` no service `CacaComentarios`).
  CLI logada aqui: `railway run --service CacaComentarios <cmd>` injeta o
  env sem expor segredo. **Nunca imprimir `DATABASE_URL`.**
- Repo local: `/root/linux/projetos/CacaComentarios`, branch **`master`**
  (não main!), remote em HTTPS.
- Seed/reparo: `scripts/seed-viraclipe-first-comment.ts`
  (`--platform ig|yt --workspace <ws> --account <id> [--text ...]`).

## Lições registradas

- Conta YT foi conectada pelo dono **depois** da primeira checagem (que
  voltou vazia) — conta conectada aparece em `YoutubeAccount`; campanha
  só existe se criada. Sempre re-checar antes de afirmar que falta algo.
- Cuidado ao criar campanha YT em loop: criar **só na conta do canal
  certo** (uma vez caiu no Caça Ofertas e foi removida).
- ViraClipe guarda texto de fallback em `pack.json: first_comments`,
  mas quem posta é a central.
