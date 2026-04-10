from __future__ import annotations

import importlib

__all__ = ["app", "create_app", "run"]


def __getattr__(name: str):
	if name in __all__:
		module = importlib.import_module(".app", __name__)
		return getattr(module, name)
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
