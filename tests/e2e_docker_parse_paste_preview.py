from __future__ import annotations

import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "http://localhost:7777"


def http_get(path: str):
    request = Request(f"{BASE_URL}{path}", method="GET")
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="ignore")
        return response.status, response.headers, body


def http_post_form(path: str, data: dict):
    payload = urlencode(data, doseq=True).encode("utf-8")
    request = Request(
        f"{BASE_URL}{path}",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="ignore")
        return response.status, response.headers, body


def wait_for(predicate, timeout_seconds: int, interval_seconds: int = 2):
    end = time.time() + timeout_seconds
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(interval_seconds)
    return None


def main() -> None:
    status, _, speakers_body = http_get("/api/speakers/edge?locale=en")
    assert status == 200, f"speakers API failed: {status}"
    speakers_payload = json.loads(speakers_body)
    speaker_count = len(speakers_payload.get("speakers", []))
    assert speaker_count > 0, "No Edge speakers returned"

    pasted_text = (
        "# Intro\n"
        "This text was pasted directly into the form.\n\n"
        "## Chapter One\n"
        "This chapter is generated from pasted content."
    )

    create_data = {
        "source_mode": "paste",
        "pasted_text": pasted_text,
        "engine": "edge",
        "speaker": "en-US-GuyNeural",
        "speed": "1.0",
        "voice_rate": "+0%",
        "voice_volume": "+0%",
        "voice_pitch": "+0Hz",
        "paragraphpause": "0",
    }
    status, _, create_html = http_post_form("/jobs/create", create_data)
    assert status == 200, f"create failed: {status} {create_html[:300]}"

    match = re.search(r'id="job-([^"]+)"', create_html)
    assert match, f"job id not found in create response: {create_html[:500]}"
    job_id = match.group(1)

    def parse_ready():
        status_code, _, live_html = http_get(f"/jobs/{job_id}/live")
        assert status_code == 200, f"live endpoint failed: {status_code}"
        if "notice error" in live_html.lower() or "failed" in live_html.lower():
            raise AssertionError(f"job failed during parse: {live_html[:500]}")
        if "Generate Selected Chapters" in live_html:
            return live_html
        return None

    parsed_html = wait_for(parse_ready, timeout_seconds=120)
    assert parsed_html, "parse stage did not reach chapter-selection state in time"

    status, _, generate_html = http_post_form(f"/jobs/{job_id}/generate", {})
    assert status == 200, f"generate enqueue failed: {status} {generate_html[:300]}"

    def generation_ready():
        status_code, _, live_html = http_get(f"/jobs/{job_id}/live")
        assert status_code == 200, f"live endpoint failed: {status_code}"
        if "notice error" in live_html.lower() or "failed" in live_html.lower():
            raise AssertionError(f"job failed during generation: {live_html[:500]}")
        if "Download" in live_html and "preview-player" in live_html:
            return live_html
        return None

    completed_html = wait_for(generation_ready, timeout_seconds=240)
    assert completed_html, "job did not complete with preview/download in time"

    status, headers, _ = http_get(f"/preview/{job_id}")
    assert status == 200, f"preview failed: {status}"
    preview_type = headers.get("Content-Type", "")
    assert preview_type.startswith("audio/mp4"), f"unexpected preview content type: {preview_type}"

    status, _, _ = http_get(f"/downloads/{job_id}")
    assert status == 200, f"download failed: {status}"

    status, _, home_html = http_get("/")
    assert status == 200, f"home failed: {status}"
    assert f"job-{job_id}" in home_html, "completed job card not visible on home page"

    print(
        json.dumps(
            {
                "job_id": job_id,
                "edge_speaker_count": speaker_count,
                "preview_content_type": preview_type,
                "home_contains_job": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
