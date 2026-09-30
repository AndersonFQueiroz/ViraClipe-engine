-- seed anti-repetição (gerado, pode commitar; sem segredos)
CREATE TABLE IF NOT EXISTS cortes(cut_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, streamer TEXT NOT NULL, t_inicio REAL NOT NULL, duracao REAL NOT NULL DEFAULT 0, chat REAL NOT NULL DEFAULT 0, audio REAL NOT NULL DEFAULT 0, viral REAL, score_final REAL NOT NULL DEFAULT 0, titulo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'scored');
CREATE TABLE IF NOT EXISTS clips_vistos(clip_id TEXT PRIMARY KEY, streamer TEXT NOT NULL, vod_id TEXT NOT NULL DEFAULT '', vod_offset REAL NOT NULL DEFAULT -1, views INTEGER NOT NULL DEFAULT 0, titulo TEXT NOT NULL DEFAULT '', visto_em TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS fila(cut_id TEXT PRIMARY KEY, mp4 TEXT NOT NULL DEFAULT '', titulo TEXT NOT NULL DEFAULT '', caption TEXT NOT NULL DEFAULT '', caption_tt TEXT NOT NULL DEFAULT '', dia_alvo TEXT NOT NULL DEFAULT '', slot INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'na_fila', criado_em TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS kv(chave TEXT PRIMARY KEY, valor TEXT NOT NULL DEFAULT '');
INSERT OR IGNORE INTO clips_vistos VALUES('QuaintSaltyOstrichDAESuppy-As_qlInAZGQmRNtD','alanzoka','2882067279',3296.0,3018,'AAAAAAAAAAAAAAAAAAAA','2026-09-28');
INSERT OR IGNORE INTO clips_vistos VALUES('ShortHonorableClintMrDestructoid-RxSdbZTV-CqeU3LM','alanzoka','2881197324',16096.0,2558,'que sustinho em kkk','2026-09-28');
INSERT OR IGNORE INTO clips_vistos VALUES('BlightedFurryCakeOSsloth-Rm1mCrMXma3Oo51j','alanzoka','2881197324',10603.0,757,'Sustinho','2026-09-29');
INSERT OR IGNORE INTO clips_vistos VALUES('FurtiveDullBobaKappaWealth-D6Pj3g62JAwQifGZ','alanzoka','2881197324',8208.0,633,'QI NEXTAGE','2026-09-29');
INSERT OR IGNORE INTO clips_vistos VALUES('AnimatedHotGrouseRickroll-EFKX5QHs6c1LotjK','tck10','2882607812',13103.0,187,'TATTOO DU SUJO','2026-09-29');
INSERT OR IGNORE INTO clips_vistos VALUES('EnticingHandsomePuffinPhilosoraptor-BHlXMD2a0uyNsD0A','alanzoka','2882067279',3314.0,467,'Que vergonha','2026-09-30');
INSERT OR IGNORE INTO clips_vistos VALUES('AthleticLivelyOryxTriHard-1LCbm4bKuWhNTWXa','coringa','2883938668',4061.0,384,'.','2026-09-30');
INSERT OR IGNORE INTO clips_vistos VALUES('BlightedSaltyLatteThunBeast-imB3tPMDA7aYDOg2','yoda','2881970045',6728.0,266,'GOLEM DE PET','2026-09-30');
INSERT OR IGNORE INTO clips_vistos VALUES('WittyArtsyTortoiseMingLee-hKPnlnuXJxiNzBfa','alanzoka','2882944021',17808.0,261,'lambidinha na costura','2026-09-30');
INSERT OR IGNORE INTO clips_vistos VALUES('FrozenShinySproutWow-kV3kmIGdzwsYMUPI','coringa','',-1.0,167,'susto','2026-09-30');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('test1-0','test1','flowpodcast',0.0,'Melhor momento de @flowpodcast','cut');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('test1-30','test1','flowpodcast',30.0,'Melhor momento de @flowpodcast','cut');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-QuaintSaltyOstrichDAESuppy-As_ql','clip:QuaintSaltyOstrichDAESuppy-As_qlInAZGQmRNtD','alanzoka',0.0,'o desespero bateu forte demais','qc_ok');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-ShortHonorableClintMrDestructoid','clip:ShortHonorableClintMrDestructoid-RxSdbZTV-CqeU3LM','alanzoka',0.0,'que sustinho em kkk','qc_ok');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('twitch:2881197324-4004','twitch:2881197324','alanzoka',4004.0,'Tomou sustinho kkkkkk','rejeitado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('twitch:2881197324-2094','twitch:2881197324','alanzoka',2094.0,'Ele ficou puto por que chamaram ele de cego kkkkkkk','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('twitch:2881197324-2654','twitch:2881197324','alanzoka',2654.0,'Ele ficou puto por que chamaram ele de cego kkkkkk','rejeitado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('twitch:2881197324-9898','twitch:2881197324','alanzoka',9898.0,'A carinha dele kkkkk','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('twitch:2881197324-2364','twitch:2881197324','alanzoka',2364.0,'Melhor momento de @alanzoka','rejeitado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-BlightedFurryCakeOSsloth-Rm1mCrM','clip:BlightedFurryCakeOSsloth-Rm1mCrMXma3Oo51j','alanzoka',0.0,'INFARTO AO VIVO','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-FurtiveDullBobaKappaWealth-D6Pj3','clip:FurtiveDullBobaKappaWealth-D6Pj3g62JAwQifGZ','alanzoka',0.0,'BURRO PRA CARALHO','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-AnimatedHotGrouseRickroll-EFKX5Q','clip:AnimatedHotGrouseRickroll-EFKX5QHs6c1LotjK','tck10',0.0,'sujo meteu o louco','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-EnticingHandsomePuffinPhilosorap','clip:EnticingHandsomePuffinPhilosoraptor-BHlXMD2a0uyNsD0A','alanzoka',0.0,'vergonha alheia demais','qc_ok');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-AthleticLivelyOryxTriHard-1LCbm4','clip:AthleticLivelyOryxTriHard-1LCbm4bKuWhNTWXa','coringa',0.0,'passou vergonha ao vivo','qc_ok');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-BlightedSaltyLatteThunBeast-imB3','clip:BlightedSaltyLatteThunBeast-imB3tPMDA7aYDOg2','yoda',0.0,'o bicho solto','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-WittyArtsyTortoiseMingLee-hKPnln','clip:WittyArtsyTortoiseMingLee-hKPnlnuXJxiNzBfa','alanzoka',0.0,'que isso mano','agendado');
INSERT OR IGNORE INTO cortes(cut_id, video_id, streamer, t_inicio, titulo, status) VALUES('clip-FrozenShinySproutWow-kV3kmIGdzws','clip:FrozenShinySproutWow-kV3kmIGdzwsYMUPI','coringa',0.0,'virou avestruz','agendado');
INSERT OR REPLACE INTO fila VALUES('twitch:2881197324-2654','data/factory/2026-09-28/final-twitch:2881197324-2654.mp4','Melhor momento de @alanzoka','🔥 Melhor momento de @alanzoka
🎮 @alanzoka
Créditos: @alanzoka — https://www.twitch.tv/videos/2881197324
📺 Live original: https://www.twitch.tv/videos/2881197324
#cortes #clipes #livetwitch #melhoresmomentos #viral
@viraclipe.oficial','Melhor momento de @alanzoka
@alanzoka 🔥
#cortes #clipes #livetwitch
@viraclipe.oficial','2026-09-28',4,'agendado','2026-09-28');
INSERT OR REPLACE INTO fila VALUES('twitch:2881197324-9898','data/factory/2026-09-28/final-twitch:2881197324-9898.mp4','A carinha dele kkkkk','🔥 A carinha dele kkkkk
🎮 @alanzoka
@alanzoka
não tankei foi nada mano kkkkkk
#alanzoka #clips #twitch #humor
@viraclipe.oficial','A carinha dele kkkkk
@alanzoka 🔥
#alanzoka #clips #twitch #humor
@viraclipe.oficial','2026-09-29',0,'agendado','2026-09-28');
INSERT OR REPLACE INTO fila VALUES('twitch:2881197324-2094','data/factory/2026-09-28/final-twitch:2881197324-2094.mp4','Ele ficou puto por que chamaram ele de cego kkkkkkk','🔥 Ele ficou puto por que chamaram ele de cego kkkkkkk
🎮 @alanzoka
Créditos: @alanzoka — https://www.twitch.tv/videos/2881197324
#cortes #clipes #livetwitch #melhoresmomentos #viral
@viraclipe.oficial','Ele ficou puto por que chamaram ele de cego kkkkkkk
@alanzoka 🔥
#cortes #clipes #livetwitch
@viraclipe.oficial','2026-09-29',1,'agendado','2026-09-28');
INSERT OR REPLACE INTO fila VALUES('clip-BlightedFurryCakeOSsloth-Rm1mCrM','data/factory/2026-09-29/final-clip-BlightedFurryCakeOSsloth-Rm1mCrM.mp4','@alanzoka — INFARTO AO VIVO','🔥 INFARTO AO VIVO
🎮 @alanzoka
@alanzoka
quase de vasco por causa de um barulho
#alanzoka #sustinho #streamer #humor
@viraclipe.oficial','INFARTO AO VIVO
@alanzoka 🔥
#alanzoka #sustinho #streamer #humor
@viraclipe.oficial','2026-09-29',3,'agendado','2026-09-29');
INSERT OR REPLACE INTO fila VALUES('clip-FurtiveDullBobaKappaWealth-D6Pj3','data/factory/2026-09-29/final-clip-FurtiveDullBobaKappaWealth-D6Pj3.mp4','@alanzoka — BURRO PRA CARALHO','🔥 BURRO PRA CARALHO
🎮 @alanzoka
@alanzoka
zerou a escala de QI
#alanzoka #fail #engraçado #twitch
@viraclipe.oficial','BURRO PRA CARALHO
@alanzoka 🔥
#alanzoka #fail #engraçado #twitch
@viraclipe.oficial','2026-09-29',4,'agendado','2026-09-29');
INSERT OR REPLACE INTO fila VALUES('clip-AnimatedHotGrouseRickroll-EFKX5Q','data/factory/2026-09-29/final-clip-AnimatedHotGrouseRickroll-EFKX5Q.mp4','@tck10 — sujo meteu o louco','🔥 sujo meteu o louco
🎮 @tck10
@tck10
maluco não existe
#tck10 #valorant #clips #twitch
@viraclipe.oficial','sujo meteu o louco
@tck10 🔥
#tck10 #valorant #clips #twitch
@viraclipe.oficial','2026-09-29',2,'agendado','2026-09-29');
INSERT OR REPLACE INTO fila VALUES('clip-BlightedSaltyLatteThunBeast-imB3','data/factory/2026-09-30/final-clip-BlightedSaltyLatteThunBeast-imB3.mp4','@yoda — o bicho solto','🔥 o bicho solto
🎮 @yoda
@yoda o mano tá tankando nada bizarro
#yoda #lolbr #twitchbr #clipes
@viraclipe.oficial','o bicho solto
@yoda 🔥
#yoda #lolbr #twitchbr #clipes
@viraclipe.oficial','2026-09-30',2,'agendado','2026-09-30');
INSERT OR REPLACE INTO fila VALUES('clip-WittyArtsyTortoiseMingLee-hKPnln','data/factory/2026-09-30/final-clip-WittyArtsyTortoiseMingLee-hKPnln.mp4','@alanzoka — que isso mano','🔥 que isso mano
🎮 @alanzoka
@alanzoka
quando o jogo passa dos limites
#alanzoka #gameplay #humor #twitch
@viraclipe.oficial','que isso mano
@alanzoka 🔥
#alanzoka #gameplay #humor #twitch
@viraclipe.oficial','2026-09-30',3,'agendado','2026-09-30');
INSERT OR REPLACE INTO fila VALUES('clip-FrozenShinySproutWow-kV3kmIGdzws','data/factory/2026-09-30/final-clip-FrozenShinySproutWow-kV3kmIGdzws.mp4','@coringa — virou avestruz','🔥 virou avestruz
🎮 @coringa
@coringa
meteu o louco e sumiu da call
#coringa #loud #clip #stream
@viraclipe.oficial','virou avestruz
@coringa 🔥
#coringa #loud #clip #stream
@viraclipe.oficial','2026-09-30',4,'agendado','2026-09-30');
INSERT OR REPLACE INTO fila VALUES('clip-EnticingHandsomePuffinPhilosorap','data/factory/2026-09-30/final-clip-EnticingHandsomePuffinPhilosorap.mp4','@alanzoka — vergonha alheia demais','🔥 vergonha alheia demais
🎮 @alanzoka
@alanzoka
intankavel esse momento
#alanzoka #twitch #humor #clips
@viraclipe.oficial','vergonha alheia demais
@alanzoka 🔥
#alanzoka #twitch #humor #clips
@viraclipe.oficial','2026-10-01',0,'agendado','2026-09-30');
INSERT OR REPLACE INTO fila VALUES('clip-AthleticLivelyOryxTriHard-1LCbm4','data/factory/2026-09-30/final-clip-AthleticLivelyOryxTriHard-1LCbm4.mp4','@coringa — passou vergonha ao vivo','🔥 passou vergonha ao vivo
🎮 @coringa
@coringa
maluco não tankou o que aconteceu
#coringa #gtarp #clipes #twitch
@viraclipe.oficial','passou vergonha ao vivo
@coringa 🔥
#coringa #gtarp #clipes #twitch
@viraclipe.oficial','2026-10-01',1,'agendado','2026-09-30');
INSERT OR REPLACE INTO kv VALUES('tg_offset','9999999999');
