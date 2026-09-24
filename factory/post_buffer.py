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
