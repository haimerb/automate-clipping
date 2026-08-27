from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

STOPWORDS = {
    "a", "al", "ante", "como", "con", "de", "del", "el", "en", "entre", "hacia",
    "para", "por", "que", "segun", "sin", "sobre", "tras", "y", "o", "e", "u",
    "ni", "pero", "aunque", "si", "sino", "porque", "cuando", "donde", "cual",
    "quien", "cuyo", "este", "esta", "estos", "estas", "ese", "esa", "esos",
    "esas", "aquel", "aquella", "ello", "le", "me", "te", "se", "nos", "os",
    "lo", "la", "los", "las", "mi", "tu", "su", "mis", "tus", "sus", "nuestro",
    "nuestra", "nuestros", "nuestras", "vuestro", "vuestra", "yo", "tu", "el",
    "ella", "nosotros", "nosotras", "vosotros", "vosotras", "ellos", "ellas",
    "ser", "estar", "haber", "tener", "hacer", "es", "son", "era", "eran",
    "fue", "fueron", "sido", "siendo", "estaba", "estaban", "estabamos",
    "estan", "esta", "estoy", "hay", "ha", "han", "he", "hemos", "habia",
    "habian", "sea", "sean", "somos", "sois", "eres", "tambien", "mas",
    "menos", "muy", "mucho", "mucha", "muchos", "muchas", "bien", "mal", "ya",
    "hoy", "aqui", "alli", "entonces", "despues", "antes", "asi", "tan",
    "tal", "cada", "otro", "otros", "otra", "otras", "unos", "unas", "uno",
    "una", "eh", "su",
}

FILLERS = {"um", "eh", "mmm", "mh", "ajam", "este", "osea", "bueno", "pues", "como", "mira", "oye"}

HOOK_WORDS = {
    "clave", "conclusion", "decision", "leccion", "error", "errores",
    "sorpresa", "sorprendente", "mejor", "peor", "historia", "funciono",
    "funciona", "funcionar", "fallo", "fracaso", "fracasar", "consejo",
    "empezo", "empieza", "conto", "pago", "paga", "cambio", "lanzo",
    "lanzamiento", "vendio", "anuncio", "campana", "cliente", "clientes",
    "presupuesto", "plazo", "apertura", "audiencia", "verdad", "verdadero",
    "importante", "nunca", "siempre", "primero", "primera", "secreto",
    "secreta", "momento", "definitivo", "problema", "truco", "regla",
    "nadie", "nada", "todo", "todos",
}

TOP_N = 10
MIN_LEN = 10.0

FORMAT_LIMITS: dict[str, tuple[float, float]] = {
    "youtube_shorts": (15.0, 58.0),
    "tiktok": (15.0, 58.0),
    "facebook_reels": (15.0, 58.0),
    "instagram_reels": (15.0, 58.0),
    "youtube": (15.0, 180.0),
    "otros": (15.0, 120.0),
}


def _limits_for(platform: str | None) -> tuple[float, float]:
    return FORMAT_LIMITS.get(platform or "", (6.0, 120.0))

_TOKEN_RE = re.compile(r"[^\W\d_]+")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(_normalize(text))


def _content_words(text: str) -> list[str]:
    return [t for t in _tokenize(text) if t not in STOPWORDS and t not in FILLERS and len(t) > 2]


def detect_clips(
    segments: list[dict], top_n: int = TOP_N, platform: str | None = None
) -> list[dict]:
    segs = [s for s in segments if s.get("text") and s.get("end", 0) > s.get("start", 0)]
    if not segs:
        return []

    MIN_LEN, MAX_LEN = _limits_for(platform)

    df: Counter = Counter()
    for s in segs:
        for w in set(_content_words(s["text"])):
            df[w] += 1

    n = len(segs)
    significance = {w: math.log(1 + n / max(1, c)) for w, c in df.items()}

    scores: list[float] = []
    for s in segs:
        toks = _tokenize(s["text"])
        content = [t for t in toks if t in significance]
        if not content:
            scores.append(0.0)
            continue
        mean_sig = sum(significance[t] for t in content) / len(content)
        density = len(content) / max(1.0, s["end"] - s["start"])
        hook = 0.8 if any(t in HOOK_WORDS for t in content) else 0.0
        filler_frac = sum(1 for t in toks if t in FILLERS) / max(1, len(toks))
        score = mean_sig * min(1.2, density * 2.2) + hook - filler_frac * 0.6
        scores.append(max(0.0, score))

    max_score = max(scores, default=0.0)
    if max_score <= 0.0:
        return []
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std = variance ** 0.5
    open_thresh = mean + 0.3 * std
    extend_thresh = max(0.0, mean - 0.3 * std)

    raw: list[dict] = []
    open_clip: dict | None = None

    def close_clip() -> None:
        nonlocal open_clip
        if open_clip is None:
            return
        raw.append(open_clip)
        open_clip = None

    for i, s in enumerate(segs):
        sc = scores[i]
        if open_clip is None:
            content = set(_content_words(s["text"]))
            has_hook = bool(content & HOOK_WORDS)
            if sc >= open_thresh and has_hook:
                open_clip = {
                    "start": s["start"], "end": s["end"], "score": sc,
                    "texts": [s["text"]],
                }
            continue
        gap = s["start"] - open_clip["end"]
        too_long = (open_clip["end"] - open_clip["start"]) > MAX_LEN
        # Extend if not too long, even with moderate gaps
        if too_long or gap > 10.0:
            close_clip()
            content = set(_content_words(s["text"]))
            has_hook = bool(content & HOOK_WORDS)
            if sc >= open_thresh and has_hook:
                open_clip = {
                    "start": s["start"], "end": s["end"], "score": sc,
                    "texts": [s["text"]],
                }
            continue
        # Extend current clip even with weak segments if not too long
        open_clip["end"] = s["end"]
        open_clip["score"] += sc
        open_clip["texts"].append(s["text"])
    close_clip()

    clips: list[dict] = []
    for c in raw:
        dur = c["end"] - c["start"]
        if dur < MIN_LEN:
            continue
        c["end"] = min(c["end"], c["start"] + MAX_LEN)
        c["script"] = " ".join(c["texts"])
        clips.append(c)

    clips.sort(key=lambda c: c["score"], reverse=True)
    clips = clips[:top_n]
    clips.sort(key=lambda c: c["start"])

    for c in clips:
        c["title"] = _make_title(c["script"])
        c["line"] = _make_line(c["script"], significance)
        c["duration"] = round(c["end"] - c["start"], 3)
        c["start"] = round(c["start"], 3)
        c["end"] = round(c["end"], 3)
        c["score"] = round(c["score"], 3)
    return clips


def _make_title(script: str) -> str:
    first_sentence = script.split(".")[0]
    words = [t for t in _content_words(first_sentence)]
    frag = " ".join(words[:6]).strip()
    if not frag:
        frag = "Momento clave"
    return frag[:1].upper() + frag[1:]


def _make_line(script: str, significance: dict[str, float]) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    best: tuple[str, float] | None = None
    for sent in sentences:
        content = [t for t in _content_words(sent) if t in significance]
        if not content:
            continue
        score = sum(significance[t] for t in content) / len(content)
        if best is None or score > best[1]:
            best = (sent, score)
    return best[0] if best else script
