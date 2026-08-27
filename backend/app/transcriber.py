from __future__ import annotations

import json
import os
import random
import zlib

import httpx

_NORMAL_SENTENCES = [
    "Y luego hablamos de cómo terminó el proyecto al final, y fue mucho trabajo pero valió la pena.",
    "El equipo pasó un par de semanas probando enfoques distintos antes de dar con el correcto.",
    "Mantuvimos la lista de cortes en una carpeta compartida para revisar cada ajuste.",
    "La mayoría de las grabaciones duran más de lo que la gente espera, así que planeamos la estructura por adelantado.",
    "Los primeros cortes fueron toscos, pero cada pasada hizo que el ritmo fuera más ajustado.",
    "Probamos varios formatos hasta encontrar uno que se sintiera natural frente a la cámara.",
    "Lo que nos llamó la atención fue cuánto valoró la gente los momentos sin pulir.",
    "Revisamos cada clip contra las notas originales antes de enviar la versión final.",
    "La segunda pasada consistió en recortar las pausas y las repeticiones.",
    "Anotamos lo que dio resultado y lo que no, para acelerar el siguiente proyecto.",
    "Cuando miramos los números nos dimos cuenta de que el engagement subió un cuarenta por ciento solo con cambiar el orden del video.",
    "El algoritmo de YouTube premia los primeros treinta segundos entonces pusimos lo mejor al inicio.",
    "Muchos creadores cometen el error de no poner subtítulos y eso les cuesta la mitad de las vistas.",
    "La clave está en narrar como si le hablaras a un amigo, nada de lenguaje corporativo o formal.",
    "Probamos a publicar a las seis de la tarde y los lunes pero el mejor día fue el miércoles a las ocho de la noche.",
    "El thumbnail es lo primero que ve la gente y si no tiene contraste nadie hace clic.",
    "Un error común es grabar sin-planear entonces el video se siente largo y aburrido.",
    "La energía que transmites al principio define si se quedan o se van en los primeros cinco segundos.",
    "Empezamos a usar cortes rápidos entre frases y el tiempo de retención aumentó notablemente.",
    "Si no tienes gancho en la primera oración ya perdiste al espectador.",
    "Lo que más funciona es contar una historia personal, la gente conecta con experiencias reales.",
    "El SEO en YouTube es distinto al de Google, hay que pensar en cómo la gente busca en video.",
    "Cada video que subimos tuvo un propósito distinto y eso nos ayudó a crecer más rápido.",
    "No se trata de frecuencia sino de consistencia, mejor tres videos buenos que siete mediocres.",
    "Los primeros mil suscriptores son los más difíciles porque nadie te conoce todavía.",
]

_HOOK_SENTENCES = [
    "La conclusión clave es que esta fue la decisión más importante que tomamos en todo el año.",
    "Esto es lo que nadie te cuenta: la primera versión simplemente fracasó.",
    "La mejor lección de ese proyecto fue aprender a decir que no al cliente equivocado desde el principio.",
    "El secreto de una buena edición es saber exactamente qué dejar fuera, y eso lo dominamos.",
    "Nuestro primer lanzamiento real nos enseñó la regla más importante de todas: empieza con tu audiencia.",
    "El mayor error que cometimos fue esconder nuestra mejor historia a mitad de la grabación.",
    "Nunca subestimes lo que importa un buen inicio, porque lo decide todo.",
    "Por fin le dijimos la verdad al cliente sobre su idea favorita, y la campaña funcionó.",
    "La verdad incómoda es que el noventa por ciento de los creadores abandonan antes del tercer video.",
    "Si estás haciendo esto entonces estás perdiendo tiempo y dinero, te lo explico ahora.",
    "El error más grande que veo en los principiantes es copiar lo que hacen los grandes sin entender por qué funciona.",
    "Lo que voy a decir ahora cambió completamente mi forma de crear contenido.",
    "Nadie te dice esto pero la clave no es la calidad del equipo sino la claridad del mensaje.",
    "Si no estás usando esto entonces estás dejando dinero sobre la mesa.",
    "Esto es exactamente lo que separa a los que crecen rápido de los que se estancan.",
]


class MockTranscriber:
    """Deterministic fake transcription so the whole pipeline runs without a model."""

    name = "mock"

    def __init__(self) -> None:
        self.name = "mock"

    def transcribe(self, path: str, duration: float) -> list[dict]:
        seed = zlib.crc32(str(path).encode("utf-8"))
        rng = random.Random(seed)
        segments: list[dict] = []
        t = 0.0
        # Generate more key moments spread throughout the video
        num_keys = rng.randint(4, 7)
        key_interval = duration / num_keys
        next_key = key_interval
        while t < duration - 3.0:
            if t >= next_key:
                # Generate a cluster of hook sentences (engaging content)
                burst = rng.randint(3, 5)
                for _ in range(burst):
                    seg_len = min(rng.uniform(8.0, 15.0), duration - t - 2.0)
                    if seg_len < 3.0:
                        break
                    segments.append({"start": t, "end": t + seg_len, "text": rng.choice(_HOOK_SENTENCES)})
                    t += seg_len + rng.uniform(0.3, 0.8)
                next_key += key_interval
                t += rng.uniform(3.0, 6.0)
                continue
            # Normal sentences with longer duration
            seg_len = min(rng.uniform(6.0, 12.0), duration - t - 2.0)
            if seg_len < 3.0:
                break
            segments.append({"start": t, "end": t + seg_len, "text": rng.choice(_NORMAL_SENTENCES)})
            t += seg_len + rng.uniform(1.0, 2.0)
        return segments


class WhisperTranscriber:
    """Real speech-to-text via faster-whisper. Imported lazily."""

    name = "whisper"

    def __init__(self, model_size: str | None = None, device: str = "cpu", compute_type: str = "int8") -> None:
        from faster_whisper import WhisperModel

        self.name = f"whisper-{model_size or 'base'}"
        self._model = WhisperModel(model_size or "base", device=device, compute_type=compute_type)

    def transcribe(self, path: str, duration: float | None = None) -> list[dict]:
        import logging
        log = logging.getLogger(__name__)
        log.info("Whisper: transcribing %s (duration=%.1f)", path, duration or 0)
        segments, info = self._model.transcribe(
            str(path),
            vad_filter=False,
            language="es",
        )
        out: list[dict] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                out.append({"start": seg.start, "end": seg.end, "text": text})
        log.info("Whisper: detected language=%s prob=%.2f, segments=%d",
                 info.language, info.language_probability, len(out))
        for s in out[:3]:
            log.info("  [%s-%s] %s", round(s["start"],1), round(s["end"],1), s["text"][:80])
        return out


class GroqWhisperTranscriber:
    """Transcribe audio via Groq Whisper API (fast, free tier available)."""

    name = "groq-whisper"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.environ.get("EDGETAPE_GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
        self.api_key = api_key or os.environ.get("EDGETAPE_GROQ_API_KEY")
        self.name = f"groq-whisper-{self.model}"

    def transcribe(self, path: str, duration: float | None = None) -> list[dict]:
        import tempfile
        from pathlib import Path

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        file_path = Path(path)
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "audio/wav")}
            data = {"model": self.model, "language": "es", "response_format": "verbose_json"}
            resp = httpx.post(url, headers=headers, files=files, data=data, timeout=120.0)

        resp.raise_for_status()
        result = resp.json()

        # Parse segments from verbose_json response
        segments = []
        for seg in result.get("segments", []):
            text = seg.get("text", "").strip()
            if text:
                segments.append({
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": text,
                })

        # If no segments, try to parse from text
        if not segments and result.get("text"):
            full_text = result["text"]
            # Split into rough segments by sentence boundaries
            import re
            sentences = re.split(r'(?<=[.!?])\s+', full_text)
            t = 0.0
            for sentence in sentences:
                if not sentence.strip():
                    continue
                seg_len = min(len(sentence.split()) * 0.4, 10.0)
                segments.append({"start": t, "end": t + seg_len, "text": sentence.strip()})
                t += seg_len + 0.3

        return segments


def build_transcriber() -> MockTranscriber | WhisperTranscriber | GroqWhisperTranscriber:
    if os.environ.get("EDGETAPE_MOCK_TRANSCRIBE") == "1":
        return MockTranscriber()

    # 1. Groq Whisper (gratis, rápido, sin GPU)
    if os.environ.get("EDGETAPE_GROQ_API_KEY"):
        try:
            return GroqWhisperTranscriber()
        except Exception:
            pass  # Fall back to local

    # 2. faster-whisper local (requiere modelo instalado)
    try:
        return WhisperTranscriber(os.environ.get("WHISPER_MODEL"))
    except ImportError:
        return MockTranscriber()
