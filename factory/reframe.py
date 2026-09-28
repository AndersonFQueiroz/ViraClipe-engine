"""Reframe inteligente: acha o rosto e monta split gameplay+facecam.

Layout split (padrão dos canais de corte): topo 720x720 gameplay (crop
central) + base 720x560 facecam (crop no rosto ampliado) = 720x1280.
Sem rosto ou sem OpenCV: fallback p/ crop central 9:16 (nunca quebra o dia).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

SAMPLE_FPS = 1.0
DETECT_WIDTH = 640
TOP_W, TOP_H = 720, 720
BOT_W, BOT_H = 720, 560
FACE_BOX = 560  # lado do crop quadrado no rosto (espaço 1280x720)


def _cascade():
    """Haar cascade frontal (vem com o opencv 4.x, sem download)."""
    import cv2

    if not hasattr(cv2, "CascadeClassifier"):
        return None
    path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not path.exists():
        return None
    try:
        return cv2.CascadeClassifier(str(path))
    except Exception:
        return None


def sample_centers(mp4: Path, t_inicio: float, duracao: float,
                   runner=subprocess.run) -> list[tuple[float, float, float]]:
    """Retorna [(cx, cy, size)] dos maiores rostos por frame amostrado.

    Coordenadas no espaço 1280x720. Lista vazia = sem rosto/sem cv2.
    """
    try:
        import cv2
    except Exception:
        return []
    cascade = _cascade()
    if cascade is None:
        return []
    centers: list[tuple[float, float, float]] = []
    with tempfile.TemporaryDirectory(prefix="reframe-") as tmp:
        out_pat = str(Path(tmp) / "f-%03d.jpg")
        try:
            r = runner(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{t_inicio:.1f}", "-t", f"{float(duracao):.1f}",
                 "-i", str(mp4), "-vf", f"fps={SAMPLE_FPS},scale={DETECT_WIDTH}:-1",
                 "-q:v", "4", out_pat],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                return []
        except Exception:
            return []
        scale = 1280.0 / DETECT_WIDTH
        for jpg in sorted(Path(tmp).glob("f-*.jpg")):
            try:
                img = cv2.imread(str(jpg), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                faces = cascade.detectMultiScale(img, scaleFactor=1.2, minNeighbors=5,
                                                 minSize=(40, 40))
                if len(faces) == 0:
                    continue
                x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
                centers.append(((float(x) + w / 2) * scale,
                                (float(y) + h / 2) * scale,
                                float(max(w, h)) * scale))
            except Exception:
                continue
    return centers


def median_box(centers: list[tuple[float, float, float]],
               src_w: int = 1280, src_h: int = 720,
               box: int = FACE_BOX) -> tuple[int, int, int, int] | None:
    """Caixa quadrada `box` centrada na mediana dos rostos (clamp + par)."""
    if not centers:
        return None
    xs = sorted(c[0] for c in centers)
    ys = sorted(c[1] for c in centers)
    cx, cy = xs[len(xs) // 2], ys[len(ys) // 2]
    x = min(max(int(cx - box / 2), 0), max(src_w - box, 0))
    y = min(max(int(cy - box / 2), 0), max(src_h - box, 0))
    x -= x % 2
    y -= y % 2
    return x, y, box, box


def find_face_box(mp4: Path, t_inicio: float, duracao: float,
                  runner=subprocess.run) -> tuple[int, int, int, int] | None:
    """Pipeline completo: amostra + mediana. None = usar crop central."""
    return median_box(sample_centers(mp4, t_inicio, duracao, runner=runner))


def split_filter(face_box: tuple[int, int, int, int] | None) -> str | None:
    """Filtro split gameplay+face (normaliza p/ 1280x720 antes). None = fallback."""
    if face_box is None:
        return None
    fx, fy, fw, fh = face_box
    return (
        "scale=1280:720,split=2[game][face];"
        f"[game]crop={TOP_W}:{TOP_H}:(in_w-{TOP_W})/2:(in_h-{TOP_H})/2,scale={TOP_W}:{TOP_H}[top];"
        f"[face]crop={fw}:{fh}:{fx}:{fy},scale={BOT_W}:{BOT_H}[bot];"
        "[top][bot]vstack"
    )
