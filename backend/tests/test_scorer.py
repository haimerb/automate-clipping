from __future__ import annotations

from app.scorer import MIN_LEN, detect_clips


def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


NORMAL = "Y luego hablamos de cómo terminó el proyecto al final y fue mucho trabajo pero valió la pena."
HOOK = "La conclusión clave es que esta fue la decisión más importante que tomamos en todo el año."


def _base_transcript() -> list[dict]:
    segs = []
    t = 0.0
    for i in range(40):
        text = NORMAL if i % 5 else HOOK
        segs.append(_seg(t, t + 8.0, text))
        t += 9.0
    return segs


def test_detects_at_least_one_clip() -> None:
    clips = detect_clips(_base_transcript())
    assert clips, "expected at least one detected clip"
    assert all(c["start"] < c["end"] for c in clips)


def test_clips_are_sorted_by_start() -> None:
    clips = detect_clips(_base_transcript())
    starts = [c["start"] for c in clips]
    assert starts == sorted(starts)


def test_clips_have_content_fields() -> None:
    clips = detect_clips(_base_transcript())
    for c in clips:
        assert c["title"]
        assert c["line"]
        assert c["script"]
        assert c["duration"] >= MIN_LEN
        assert len(c["script"]) >= len(c["line"])


def test_top_n_respected() -> None:
    clips = detect_clips(_base_transcript(), top_n=3)
    assert len(clips) <= 3


def test_empty_transcript_yields_no_clips() -> None:
    assert detect_clips([]) == []


def test_quiet_transcript_yields_fewer_or_no_clips() -> None:
    quiet = [_seg(i * 9.0, i * 9.0 + 8.0, "um eh pues bueno este osea mmm") for i in range(20)]
    clips = detect_clips(quiet)
    assert not any(c["score"] > 0 for c in clips)
