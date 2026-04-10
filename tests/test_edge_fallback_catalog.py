from __future__ import annotations

from ebook2m4b.tts_providers.edge.fallback_catalog import FALLBACK_EDGE_VOICES, fallback_voice_rows


def test_edge_fallback_catalog_is_large_and_structured() -> None:
    assert len(FALLBACK_EDGE_VOICES) > 300

    rows = fallback_voice_rows()
    assert len(rows) == len(FALLBACK_EDGE_VOICES)

    english = next(row for row in rows if row["ShortName"] == "en-US-GuyNeural")
    japanese = next(row for row in rows if row["ShortName"] == "ja-JP-NanamiNeural")

    assert english["Locale"] == "en-US"
    assert japanese["Locale"] == "ja-JP"
