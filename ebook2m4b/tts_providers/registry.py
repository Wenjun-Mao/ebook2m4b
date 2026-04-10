from __future__ import annotations

from .base import EngineInfo, TTSEngine
from .edge.provider import EdgeTTSProvider
from .kokoro.provider import KokoroEngine

ENGINE_FACTORIES: dict[str, type[TTSEngine]] = {
    "kokoro": KokoroEngine,
    "edge": EdgeTTSProvider,
}


def get_engine(engine_id: str) -> TTSEngine:
    normalized = (engine_id or "").strip().lower() or "kokoro"
    factory = ENGINE_FACTORIES.get(normalized)
    if factory is None:
        supported = ", ".join(sorted(ENGINE_FACTORIES))
        raise ValueError(f"Unsupported engine '{engine_id}'. Supported engines: {supported}")
    return factory()


def get_engine_info_list() -> list[EngineInfo]:
    infos: list[EngineInfo] = []
    for engine_id in sorted(ENGINE_FACTORIES):
        engine = ENGINE_FACTORIES[engine_id]()
        infos.append(engine.info)
    return infos
