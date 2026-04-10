from __future__ import annotations

from pathlib import Path

from ebook2m4b.parsers import parse_text_book


def test_parse_text_book_preserves_markdown_heading_levels(tmp_path: Path) -> None:
    source_path = tmp_path / "hierarchy.txt"
    source_path.write_text(
        """
# Book Title
Top level paragraph.

## Chapter 1
Chapter paragraph.

### Scene 1
Scene paragraph.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    book = parse_text_book(source_path)

    assert [chapter.title for chapter in book.chapters] == ["Book Title", "Chapter 1", "Scene 1"]
    assert [chapter.level for chapter in book.chapters] == [1, 2, 3]
    assert book.paragraph_total > 0
