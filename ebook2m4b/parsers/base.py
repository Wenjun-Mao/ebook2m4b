from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .processing import BookData, ParserOptions


class BookParser(ABC):
    @abstractmethod
    def parse(self, source_path: Path, options: ParserOptions) -> BookData:
        raise NotImplementedError
