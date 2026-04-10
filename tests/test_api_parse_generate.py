from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from ebook2m4b.jobs import get_job
from ebook2m4b.settings import Settings
from ebook2m4b.tts_providers.base import SpeakerProfile
from ebook2m4b.web_ui.app import create_app


class DummyEngine:
    def get_speaker(self, speaker_id: str) -> SpeakerProfile:
        return SpeakerProfile(
            id=speaker_id,
            display_name=speaker_id,
            language="English",
            language_code="en-US",
            gender="Unknown",
        )

    def synthesize(self, **kwargs):
        book = kwargs["book"]
        work_dir = kwargs["work_dir"]
        progress_callback = kwargs["progress_callback"]

        progress_callback(0, book.chapter_total, 0, book.paragraph_total)
        progress_callback(book.chapter_total, book.chapter_total, book.paragraph_total, book.paragraph_total)

        output_path = work_dir / "api-dummy-output.m4b"
        output_path.write_bytes(b"dummy")
        return output_path


def test_api_parse_then_generate_inline(monkeypatch, test_settings: Settings) -> None:
    pasted_text = """
# Intro
This is the introduction.

## Chapter One
This is chapter one.
""".strip()

    monkeypatch.setattr("ebook2m4b.conversion.get_engine", lambda _engine_id: DummyEngine())
    monkeypatch.setattr("ebook2m4b.jobs.get_settings", lambda: test_settings)

    app = create_app(test_settings)
    client = TestClient(app)

    create_response = client.post(
        "/jobs/create",
        data={
            "source_mode": "paste",
            "pasted_text": pasted_text,
            "engine": "kokoro",
            "speaker": "af_heart",
            "speed": "1.0",
            "voice_rate": "+0%",
            "voice_volume": "+0%",
            "voice_pitch": "+0Hz",
            "paragraphpause": "0",
        },
    )

    assert create_response.status_code == 200, create_response.text
    assert "Generate Selected Chapters" in create_response.text

    match = re.search(r'id="job-([^"]+)"', create_response.text)
    assert match is not None
    job_id = match.group(1)

    generate_response = client.post(
        f"/jobs/{job_id}/generate",
        data={"selected_chapters": ["1"]},
    )

    assert generate_response.status_code == 200
    assert "Download" in generate_response.text
    assert "<audio" in generate_response.text

    job = get_job(job_id, test_settings)
    assert job is not None
    assert job.status == "completed"
    assert job.source_kind == "txt"
    assert job.output_path is not None
    assert Path(job.output_path).exists()

    preview_response = client.get(f"/preview/{job_id}")
    assert preview_response.status_code == 200
    assert preview_response.headers.get("content-type", "").startswith("audio/mp4")

    home_before_discard = client.get("/")
    assert home_before_discard.status_code == 200
    assert f"job-{job_id}" in home_before_discard.text

    discard_response = client.post(f"/jobs/{job_id}/discard")
    assert discard_response.status_code == 200

    discarded_job = get_job(job_id, test_settings)
    assert discarded_job is not None
    assert discarded_job.status == "discarded"

    home_after_discard = client.get("/")
    assert home_after_discard.status_code == 200
    assert f"job-{job_id}" not in home_after_discard.text
