from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.media import (
    _EXPLOSIVE_FALLBACKS,
    _explosive_lines,
    _explosive_words,
    extract_multiple_thumbnails,
    extract_viral_shorts_thumbnail,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=duration=60:size=320x240:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


def test_explosive_words_trims_to_three() -> None:
    out = _explosive_words("La conclusión clave es que esta fue la decisión más importante")
    assert out == "LA CONCLUSIÓN CLAVE"
    assert len(out.split()) == 3


def test_explosive_words_emoji_stripped() -> None:
    assert _explosive_words("🎯 increíble 🔥 jugada") == "INCREÍBLE JUGADA"


def test_explosive_words_short_stays() -> None:
    assert _explosive_words(" increíble! ") == "INCREÍBLE"


def test_explosive_words_fallback_by_variant() -> None:
    assert _explosive_words("", 0) == _EXPLOSIVE_FALLBACKS[0]
    assert _explosive_words("   ", 1) == _EXPLOSIVE_FALLBACKS[1]
    assert _explosive_words("", 2) == _EXPLOSIVE_FALLBACKS[2]


def test_explosive_lines_respects_max_chars() -> None:
    assert _explosive_lines("NO LO CREERÁS", 8) == ["NO LO", "CREERÁS"]
    assert _explosive_lines("INCREÍBLE", 8) == ["INCREÍBLE"]


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def test_viral_shorts_thumbnail_is_1080x1920(sample_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "short.jpg"
    extract_viral_shorts_thumbnail(
        sample_video, at=1.0, out=out, text="La conclusión clave cambia todo", variant=0
    )
    assert out.exists()
    assert _image_size(out) == (1080, 1920)
    assert out.stat().st_size > 1000


def test_viral_shorts_thumbnail_shorter_text(sample_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "short2.jpg"
    extract_viral_shorts_thumbnail(sample_video, at=2.0, out=out, text="WOW", variant=3)
    assert out.exists()
    assert _image_size(out) == (1080, 1920)


def test_extract_multiple_first_shorts_style(sample_video: Path, tmp_path: Path) -> None:
    filenames = extract_multiple_thumbnails(
        sample_video, start=0.0, end=6.0, out_dir=tmp_path, clip_id="c1",
        count=5, text="La conclusión clave",
    )
    assert len(filenames) == 5
    # índice 0 (default) = estilo explosivo a resolución completa
    assert _image_size(tmp_path / filenames[0]) == (1080, 1920)
    assert _image_size(tmp_path / filenames[1]) == (1080, 1920)
    # último índice = dorado clásico (360 de ancho por el fixture)
    assert _image_size(tmp_path / filenames[4]) == (360, 640)