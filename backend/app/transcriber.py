from __future__ import annotations

import os
import random
import zlib

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
        key_interval = duration / rng.randint(3, 5)
        next_key = key_interval
        while t < duration - 2.0:
            if t >= next_key:
                burst = rng.randint(2, 3)
                for _ in range(burst):
                    seg_len = min(rng.uniform(4.0, 7.0), duration - t - 1.0)
                    if seg_len < 2.0:
                        break
                    segments.append({"start": t, "end": t + seg_len, "text": rng.choice(_HOOK_SENTENCES)})
                    t += seg_len + rng.uniform(0.2, 0.4)
                next_key += key_interval
                t += rng.uniform(5.0, 8.0)
                continue
            seg_len = min(rng.uniform(4.0, 9.0), duration - t - 1.0)
            if seg_len < 2.0:
                break
            segments.append({"start": t, "end": t + seg_len, "text": rng.choice(_NORMAL_SENTENCES)})
            t += seg_len + rng.uniform(1.5, 3.0)
        return segments


class WhisperTranscriber:
    """Real speech-to-text via faster-whisper. Imported lazily."""

    name = "whisper"

    def __init__(self, model_size: str | None = None, device: str = "cpu", compute_type: str = "int8") -> None:
        from faster_whisper import WhisperModel

        self.name = f"whisper-{model_size or 'base'}"
        self._model = WhisperModel(model_size or "base", device=device, compute_type=compute_type)

    def transcribe(self, path: str, duration: float | None = None) -> list[dict]:
        segments, _ = self._model.transcribe(str(path), vad_filter=True)
        out: list[dict] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                out.append({"start": seg.start, "end": seg.end, "text": text})
        return out


def build_transcriber() -> MockTranscriber | WhisperTranscriber:
    if os.environ.get("EDGETAPE_MOCK_TRANSCRIBE") == "1":
        return MockTranscriber()
    try:
        return WhisperTranscriber(os.environ.get("WHISPER_MODEL"))
    except ImportError:
        return MockTranscriber()
