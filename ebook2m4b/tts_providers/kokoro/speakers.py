from __future__ import annotations

from functools import lru_cache

from ..base import SpeakerProfile

LANGUAGE_BY_PREFIX = {
    "a": "American English",
    "b": "British English",
    "j": "Japanese",
    "z": "Mandarin Chinese",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "p": "Brazilian Portuguese",
}


VOICE_ROWS = [
    ("af_heart", "A", None),
    ("af_alloy", "C", "MM minutes"),
    ("af_aoede", "C+", "H hours"),
    ("af_bella", "A-", "HH hours"),
    ("af_jessica", "D", "MM minutes"),
    ("af_kore", "C+", "H hours"),
    ("af_nicole", "B-", "HH hours"),
    ("af_nova", "C", "MM minutes"),
    ("af_river", "D", "MM minutes"),
    ("af_sarah", "C+", "H hours"),
    ("af_sky", "C-", "M minutes"),
    ("am_adam", "F+", "H hours"),
    ("am_echo", "D", "MM minutes"),
    ("am_eric", "D", "MM minutes"),
    ("am_fenrir", "C+", "H hours"),
    ("am_liam", "D", "MM minutes"),
    ("am_michael", "C+", "H hours"),
    ("am_onyx", "D", "MM minutes"),
    ("am_puck", "C+", "H hours"),
    ("am_santa", "D-", "M minutes"),
    ("bf_alice", "D", "MM minutes"),
    ("bf_emma", "B-", "HH hours"),
    ("bf_isabella", "C", "MM minutes"),
    ("bf_lily", "D", "MM minutes"),
    ("bm_daniel", "D", "MM minutes"),
    ("bm_fable", "C", "MM minutes"),
    ("bm_george", "C", "MM minutes"),
    ("bm_lewis", "D+", "H hours"),
    ("jf_alpha", "C+", "H hours"),
    ("jf_gongitsune", "C", "MM minutes"),
    ("jf_nezumi", "C-", "M minutes"),
    ("jf_tebukuro", "C", "MM minutes"),
    ("jm_kumo", "C-", "M minutes"),
    ("zf_xiaobei", "D", "MM minutes"),
    ("zf_xiaoni", "D", "MM minutes"),
    ("zf_xiaoxiao", "D", "MM minutes"),
    ("zf_xiaoyi", "D", "MM minutes"),
    ("zm_yunjian", "D", "MM minutes"),
    ("zm_yunxi", "D", "MM minutes"),
    ("zm_yunxia", "D", "MM minutes"),
    ("zm_yunyang", "D", "MM minutes"),
    ("ef_dora", None, None),
    ("em_alex", None, None),
    ("em_santa", None, None),
    ("ff_siwis", "B-", "<11 hours"),
    ("hf_alpha", "C", "MM minutes"),
    ("hf_beta", "C", "MM minutes"),
    ("hm_omega", "C", "MM minutes"),
    ("hm_psi", "C", "MM minutes"),
    ("if_sara", "C", "MM minutes"),
    ("im_nicola", "C", "MM minutes"),
    ("pf_dora", None, None),
    ("pm_alex", None, None),
    ("pm_santa", None, None),
]


def _display_name(voice_id: str) -> str:
    voice_label = voice_id.split("_", 1)[-1].replace("_", " ").title()
    return f"{voice_label} ({voice_id})"


def _gender_from_voice_id(voice_id: str) -> str | None:
    if len(voice_id) < 2:
        return None
    marker = voice_id[1]
    if marker == "f":
        return "Female"
    if marker == "m":
        return "Male"
    return None


def _language_from_voice_id(voice_id: str) -> str:
    if not voice_id:
        return "Unknown"
    return LANGUAGE_BY_PREFIX.get(voice_id[0], "Unknown")


@lru_cache(maxsize=1)
def get_kokoro_speakers() -> list[SpeakerProfile]:
    speakers: list[SpeakerProfile] = []
    for voice_id, overall_grade, training_duration in VOICE_ROWS:
        language = _language_from_voice_id(voice_id)
        language_code = voice_id[0] if voice_id else "a"
        gender = _gender_from_voice_id(voice_id)

        speakers.append(
            SpeakerProfile(
                id=voice_id,
                display_name=_display_name(voice_id),
                language=language,
                language_code=language_code,
                gender=gender,
                overall_grade=overall_grade,
                training_duration=training_duration,
                target_quality=None,
            )
        )

    speakers.sort(key=lambda item: item.id)
    return speakers
