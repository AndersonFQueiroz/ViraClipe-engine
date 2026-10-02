"""Auto-post IG + TikTok + YouTube via Buffer (plano grátis).

AUTO-TOTAL (diferença do ReelIfy): sem trava --sim. O run_diaria chama
direto; QC + threshold + denylist são a proteção. Sem BUFFER_API_KEY
retorna exit 3 (pula, sem erro). Kwai segue manual via pack_kwai.zip.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

import requests

from . import net as _net
from . import upload_public
from config.settings import SLOTS_UTC

API = "https://api.buffer.com"
_TIMEOUT = 60
WANT = ("instagram", "tiktok", "youtube")


def _gql(token: str, query: str, variables: dict | None = None) -> dict:
    def _do() -> dict:
        r = requests.post(API, json={"query": query, "variables": variables or {}},
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"},
                          timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(str(data["errors"][0].get("message")))
        return data["data"]

    return _net.call(_do)


def channels(token: str) -> dict[str, str]:
    orgs = _gql(token, "query { account { organizations { id name } } }")
    org_list = ((orgs.get("account") or {}).get("organizations")) or []
    if not org_list:
        raise RuntimeError("sem organizações no Buffer")
    found: dict[str, str] = {}
    for org in org_list:
        chs = _gql(token, "query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id name service } }",
                   {"o": org["id"]})
        for ch in (chs.get("channels") or []):
            svc = str(ch.get("service") or "").lower()
            for w in WANT:
                if w in svc and w not in found:
                    found[w] = ch["id"]
    return found


def create_post(token: str, svc: str, channel_id: str, text: str,
                video_url: str, due_at: str, title: str) -> str:
    meta: dict = {}
    if svc == "instagram":
        meta = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    elif svc == "youtube":
        meta = {"youtube": {"title": title, "categoryId": "22"}}
    variables = {"i": {"text": text, "channelId": channel_id,
                       "schedulingType": "automatic", "mode": "customScheduled",
                       "dueAt": due_at,
                       "assets": [{"video": {"url": video_url,
                                             "metadata": {"thumbnailOffset": 2000}}}]}}
    if meta:
        variables["i"]["metadata"] = meta
    q = """mutation($i: CreatePostInput!) {
      createPost(input: $i) {
        ... on PostActionSuccess { post { id dueAt } }
        ... on MutationError { message }
      } } """
    data = _gql(token, q, variables)
    res = (data.get("createPost") or {})
    post = res.get("post")
    if post:
        return post["id"]
    raise RuntimeError(res.get("message", "erro desconhecido"))


def _org_id(token: str) -> str:
    orgs = _gql(token, "query { account { organizations { id name } } }")
    org_list = ((orgs.get("account") or {}).get("organizations")) or []
    return str((org_list[0].get("id") if org_list else "") or "")


def posts_com_erro(token: str, horas: int = 48) -> list[dict]:
    """Posts YT com erro de mídia nas últimas `horas`h (p/ auto-recovery)."""
    import datetime as _dt

    org = _org_id(token)
    if not org:
        return []
    try:
        data = _gql(token,
                    "query($o: OrganizationId!) { posts(input: {organizationId: $o})"
                    " { edges { node { id channelService dueAt error { message } } } } }",
                    {"o": org})
    except Exception:
        return []
    edges = (data.get("posts") or {}).get("edges") or []
    out = []
    for e in edges:
        n = e.get("node") or {}
        if "youtube" not in str(n.get("channelService") or "").lower():
            continue
        err = ((n.get("error") or {}).get("message") or "")
        if not err:
            continue
        try:
            due = _dt.datetime.fromisoformat(str(n.get("dueAt") or ""))
        except ValueError:
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=_dt.timezone.utc)
        age = (_dt.datetime.now(_dt.timezone.utc) - due).total_seconds() / 3600
        if 0 <= age <= horas:
            out.append({"post_id": n.get("id"), "due": str(n.get("dueAt")),
                        "error": err[:200]})
    return out


def delete_post(token: str, post_id: str) -> bool:
    try:
        data = _gql(token,
                    "mutation($i: DeletePostInput!) { deletePost(input: $i) { __typename } }",
                    {"i": {"id": post_id}})
        return "DeletePostSuccess" in json.dumps(data)
    except Exception:
        return False


def recuperar_youtube(factory_data: Path, db_path: Path, token: str = "",
                      hoje: str = "") -> dict:
    """Recupera posts YT com erro: deleta o quebrado, re-uploada fresco e
    reagenda no próximo slot livre. Retorna resumo. Nunca levanta."""
    import datetime as _dt

    from . import aprova as _ap
    from . import db as _db
    from . import upload_public as _up

    token = token or os.environ.get("BUFFER_API_KEY", "")
    if not token:
        return {"ok": False, "error": "sem BUFFER_API_KEY"}
    hoje = hoje or _dt.date.today().isoformat()
    _db.init_db(db_path)
    try:
        quebrados = posts_com_erro(token)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}"}
    rec, falhas = [], []
    for q in quebrados:
        con = _db.connect(db_path)
        try:
            row = con.execute(
                "SELECT cut_id FROM posts WHERE buffer_id=?", (q["post_id"],)).fetchone()
            cut_id = str(row["cut_id"]) if row else ""
            frow = con.execute(
                "SELECT * FROM fila WHERE cut_id=?", (cut_id,)).fetchone() if cut_id else None
        finally:
            con.close()
        if not frow:
            continue  # corte desconhecido: nada a refazer
        f = dict(frow)
        mp4 = Path(str(f.get("mp4") or ""))
        if not mp4.exists():
            continue  # runner efêmero sem o arquivo: pula (url guardada p/ futuro)
        nd, ns = _ap.proximo_slot(db_path, hoje)
        due = _ap.due_at(nd, ns)
        try:
            chans = channels(token)
            url = _up.upload(mp4)  # upload FRESCO (o antigo o YT rejeitou)
            if not url:
                raise RuntimeError("upload falhou")
            pid = create_post(token, "youtube", chans["youtube"],
                              str(f.get("caption") or "")[:2100], url, due,
                              str(f.get("titulo") or f"ViraClipe {nd}"))
            delete_post(token, q["post_id"])
        except Exception:
            falhas.append(cut_id)
            continue
        con = _db.connect(db_path)
        try:
            con.execute("INSERT OR REPLACE INTO posts(cut_id, rede, buffer_id, agendado_para)"
                        " VALUES(?,?,?,?)", (cut_id, "youtube", pid, due))
            con.execute("INSERT OR REPLACE INTO fila(cut_id, mp4, url, titulo, caption, caption_tt,"
                        " dia_alvo, slot, status, criado_em) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (cut_id, str(mp4), str(f.get("url") or ""),
                         str(f.get("titulo") or "")[:90],
                         str(f.get("caption") or "")[:2100],
                         str(f.get("caption_tt") or "")[:2100],
                         nd, ns, "agendado", hoje))
            con.commit()
            rec.append({"cut_id": cut_id, "dia": nd, "slot": ns})
        finally:
            con.close()
    return {"ok": True, "recuperados": rec, "falhas": falhas}


def main(day: str, factory_data: Path, only: list[str] | None = None,
         channels_fn=None, create_fn=None, uploader=None) -> int:
    token = os.environ.get("BUFFER_API_KEY", "")
    if not token:
        print("SEM BUFFER_API_KEY — auto-post pulado (exit 3).")
        return 3
    day_dir = factory_data / day
    pack = json.loads((day_dir / "pack.json").read_text(encoding="utf-8"))
    keys = [k for k in pack.get("videos", {}) if not only or k in only]
    if not keys:
        print("Nada para postar.")
        return 1
    chans = (channels_fn or channels)(token)
    missing = [w for w in WANT if w not in chans]
    if missing:
        print(f"Buffer: canais não conectados: {missing}")
    up = uploader or upload_public.upload
    ok, fail, records = 0, 0, []
    for key in keys:
        h, m = SLOTS_UTC[(int(key[1:]) - 1) % len(SLOTS_UTC)]
        base = _dt.date(int(day[:4]), int(day[5:7]), int(day[8:10]))
        if h == 0:
            base += _dt.timedelta(days=1)
        url = up(Path(pack["videos"][key]))
        if not url:
            print(f"upload público falhou: {key}")
            fail += 3
            continue
        due = _dt.datetime(base.year, base.month, base.day, h, m,
                           tzinfo=_dt.timezone.utc).isoformat()
        for svc in WANT:
            if svc not in chans:
                continue
            base_cap = pack.get("captions_tt", {}).get(key) if svc == "tiktok" else pack["captions"][key]
            text = (base_cap + "\n" + pack.get("cta", {}).get(svc, ""))[:2100]
            try:
                pid = (create_fn or create_post)(token, svc, chans[svc], text, url, due,
                                                 pack.get("titles", {}).get(key, f"ViraClipe {day}"))
                print(f"Buffer OK {svc}/{key}: {pid} @ {due}")
                records.append({"svc": svc, "key": key, "id": pid, "due_at": due, "url": url})
                ok += 1
            except Exception as exc:
                print(f"Buffer FALHOU {svc}/{key}: {exc}")
                records.append({"svc": svc, "key": key, "error": str(exc)[:200], "due_at": due})
                fail += 1
    (day_dir / "buffer.json").write_text(json.dumps({"ok": ok, "fail": fail, "posts": records}), encoding="utf-8")
    return 0 if ok else 1
