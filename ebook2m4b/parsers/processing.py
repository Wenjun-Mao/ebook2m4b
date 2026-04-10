from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from lxml import etree
from PIL import Image
from sentencex import segment

NAMESPACES = {
    "calibre": "http://calibre.kovidgoyal.net/2009/metadata",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "opf": "http://www.idpf.org/2007/opf",
    "u": "urn:oasis:names:tc:opendocument:xmlns:container",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

SUPPORTED_NEWLINE_MODES = {"single", "double", "none"}
SUPPORTED_TITLE_MODES = {"auto", "tag_text", "first_few"}


@dataclass(slots=True)
class ParserOptions:
    language: str = "en"
    newline_mode: str = "double"
    title_mode: str = "auto"
    remove_endnotes: bool = True
    remove_reference_numbers: bool = True
    max_segment_chars: int = 400
    min_sentence_words: int = 8


@dataclass(slots=True)
class ChapterData:
    index: int
    title: str
    paragraphs: list[str]
    level: int = 1

    @property
    def paragraph_count(self) -> int:
        return len(self.paragraphs)


@dataclass(slots=True)
class BookData:
    title: str
    author: str
    chapters: list[ChapterData]

    @property
    def chapter_total(self) -> int:
        return len(self.chapters)

    @property
    def paragraph_total(self) -> int:
        return sum(chapter.paragraph_count for chapter in self.chapters)


@dataclass(slots=True)
class PreparedTextSource:
    text_path: Path
    book: BookData
    auto_cover_path: Path | None


def _normalize_whitespace(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"[\u201c\u201d]", '"', cleaned)
    cleaned = re.sub(r"[\u2018\u2019]", "'", cleaned)
    cleaned = re.sub(r"--", ", ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]

    punctuations = [
        "。",
        "！",
        "？",
        ". ",
        "! ",
        "? ",
        ";",
        "；",
        ",",
        "，",
        ":",
        "：",
        " ",
    ]

    pieces: list[str] = []
    remaining = sentence
    while remaining:
        if len(remaining) <= max_chars:
            pieces.append(remaining)
            break

        split_index = -1
        for mark in punctuations:
            candidate = remaining[:max_chars].rfind(mark)
            if candidate >= 0:
                split_index = candidate + len(mark)
                break

        if split_index < 0:
            split_index = max_chars

        pieces.append(remaining[:split_index].strip())
        remaining = remaining[split_index:].strip()

    return [part for part in pieces if part]


def _split_sentences(text: str, language: str) -> list[str]:
    rows = [row.strip() for row in segment(language, text)]
    rows = [row for row in rows if any(char.isalnum() for char in row)]
    if rows:
        return rows

    fallback = re.split(r"(?<=[.!?])\s+", text)
    fallback = [row.strip() for row in fallback if any(char.isalnum() for char in row)]
    return fallback if fallback else [text.strip()]


def _segment_text(text: str, options: ParserOptions) -> list[str]:
    normalized = _normalize_whitespace(text)
    if not normalized or not any(char.isalnum() for char in normalized):
        return []

    if options.remove_endnotes:
        normalized = re.sub(r'(?<=[A-Za-z.,!?;"\)])\d+', "", normalized)
    if options.remove_reference_numbers:
        normalized = re.sub(r"\[\d+(\.\d+)?\]", "", normalized)

    sentence_rows = _split_sentences(normalized, options.language)

    merged_rows: list[str] = []
    index = 0
    while index < len(sentence_rows):
        sentence_text = sentence_rows[index].strip()
        words = sentence_text.split()
        if len(words) < options.min_sentence_words and index + 1 < len(sentence_rows):
            sentence_text = f"{sentence_text} {sentence_rows[index + 1].strip()}".strip()
            index += 1

        if len(sentence_text) > options.max_segment_chars:
            merged_rows.extend(_split_long_sentence(sentence_text, options.max_segment_chars))
        else:
            merged_rows.append(sentence_text)

        index += 1

    if len(merged_rows) > 1 and len(merged_rows[-1].split()) < options.min_sentence_words:
        merged_rows[-2] = f"{merged_rows[-2]} {merged_rows[-1]}".strip()
        merged_rows.pop()

    compact = [_normalize_whitespace(row) for row in merged_rows if any(char.isalnum() for char in row)]
    return [row for row in compact if row]


def _best_title_from_html(
    soup: BeautifulSoup,
    item_id: str | None,
    fallback_text: str,
    *,
    mode: str,
) -> str:
    def _tag_title() -> str | None:
        for tag_name in ("title", "h1", "h2", "h3"):
            node = soup.find(tag_name)
            if node and node.text.strip():
                return _normalize_whitespace(node.text)
        for class_name in ("chapter", "chapter-title", "title", "heading"):
            node = soup.find(class_=class_name)
            if node and node.text.strip():
                return _normalize_whitespace(node.text)
        return None

    fallback_item_title = ""
    if item_id:
        fallback_item_title = item_id.replace(".xhtml", "").replace("_", " ").strip().title()

    if mode == "tag_text":
        return _tag_title() or "<blank>"

    if mode == "first_few":
        preview = _normalize_whitespace(fallback_text)[:60].strip()
        return preview or fallback_item_title or "Untitled"

    tag_title = _tag_title()
    if tag_title and not re.fullmatch(r"\d{1,3}", tag_title):
        return tag_title

    preview = _normalize_whitespace(fallback_text)[:60].strip()
    return preview or fallback_item_title or "Untitled"


def _normalize_href(value: str | None) -> str:
    if not value:
        return ""
    normalized = str(value).strip().replace("\\", "/")
    normalized = normalized.split("#", 1)[0].split("?", 1)[0]
    return normalized.strip().lower()


def _toc_title(node: object) -> str:
    for attr in ("title", "name"):
        raw_value = getattr(node, attr, None)
        if isinstance(raw_value, str) and raw_value.strip():
            return _normalize_whitespace(raw_value)
    return ""


def _toc_href(node: object) -> str:
    for attr in ("href", "file_name"):
        raw_value = getattr(node, attr, None)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value
    if isinstance(node, str):
        return node
    return ""


def _split_toc_node(node: object) -> tuple[object, list[object]]:
    if isinstance(node, (list, tuple)):
        if len(node) == 2 and isinstance(node[1], (list, tuple)):
            return node[0], list(node[1])
        if node:
            children: list[object] = []
            for child in node[1:]:
                if isinstance(child, (list, tuple)):
                    children.extend(list(child))
            return node[0], children
    return node, []


def _flatten_toc(nodes: list[object], *, level: int = 1, rows: list[dict] | None = None) -> list[dict]:
    entries = rows if rows is not None else []
    for raw_node in nodes:
        node, children = _split_toc_node(raw_node)
        href = _normalize_href(_toc_href(node))
        if href:
            entries.append(
                {
                    "href": href,
                    "title": _toc_title(node),
                    "level": max(1, level),
                    "order": len(entries),
                }
            )
        if children:
            _flatten_toc(children, level=level + 1, rows=entries)
    return entries


def _build_toc_lookup(book) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    raw_toc = list(getattr(book, "toc", []) or [])
    for entry in _flatten_toc(raw_toc):
        href = str(entry.get("href") or "")
        if not href:
            continue
        if href not in lookup:
            lookup[href] = entry
        basename = Path(href).name.lower()
        if basename and basename not in lookup:
            lookup[basename] = entry
    return lookup


def _heading_text(node) -> str:
    if node is None:
        return ""
    text = _normalize_whitespace(node.get_text(" ", strip=False))
    if not text:
        return ""
    if re.fullmatch(r"\d{1,3}", text):
        return ""
    return text


def _heading_offset(node) -> int:
    if node is None:
        return 0
    name = str(getattr(node, "name", "")).lower()
    if name == "h2":
        return 1
    if name == "h3":
        return 2
    return 0


def _extract_segments_from_html(
    soup: BeautifulSoup,
    fallback_title: str,
    fallback_level: int,
    options: ParserOptions,
) -> list[tuple[str, int, list[str]]]:
    paragraph_nodes = soup.find_all("p")
    if not paragraph_nodes:
        paragraph_nodes = [
            node
            for node in soup.find_all("div")
            if not node.find(["p", "div"])
        ]

    segments: list[tuple[str, int, list[str]]] = []
    current_title = fallback_title
    current_level = max(1, fallback_level)
    current_units: list[str] = []

    for paragraph_node in paragraph_nodes:
        heading_node = paragraph_node.find_previous(["h1", "h2", "h3"])
        heading_title = _heading_text(heading_node)
        heading_level = max(1, fallback_level + _heading_offset(heading_node))

        if heading_title and current_units and heading_title != current_title:
            segments.append((current_title, current_level, current_units))
            current_units = []

        if heading_title:
            current_title = heading_title
            current_level = heading_level

        paragraph_units = _segment_text(paragraph_node.get_text(" ", strip=False), options)
        if paragraph_units:
            current_units.extend(paragraph_units)

    if current_units:
        segments.append((current_title, current_level, current_units))

    if segments:
        return segments

    raw_text = soup.get_text(strip=False)
    fallback_units = _fallback_units_from_raw_text(raw_text, options)
    if not fallback_units:
        return []
    return [(fallback_title, max(1, fallback_level), fallback_units)]


def _extract_cover_image(epub_path: Path) -> bytes | None:
    try:
        with zipfile.ZipFile(epub_path) as archive:
            container_xml = etree.fromstring(archive.read("META-INF/container.xml"))
            rootfile_node = container_xml.xpath(
                "/u:container/u:rootfiles/u:rootfile",
                namespaces=NAMESPACES,
            )[0]
            rootfile_path = rootfile_node.get("full-path")
            if not rootfile_path:
                return None

            package_xml = etree.fromstring(archive.read(rootfile_path))
            cover_meta = package_xml.xpath(
                "//opf:metadata/opf:meta[@name='cover']",
                namespaces=NAMESPACES,
            )
            if not cover_meta:
                return None

            cover_id = cover_meta[0].get("content")
            if not cover_id:
                return None

            cover_item = package_xml.xpath(
                f"//opf:manifest/opf:item[@id='{cover_id}']",
                namespaces=NAMESPACES,
            )
            if not cover_item:
                return None

            cover_href = cover_item[0].get("href")
            if not cover_href:
                return None

            cover_path = Path(rootfile_path).parent / cover_href
            return archive.read(cover_path.as_posix())
    except Exception:  # noqa: BLE001
        return None


def _fallback_units_from_raw_text(raw_text: str, options: ParserOptions) -> list[str]:
    trimmed = raw_text.strip()
    if not trimmed:
        return []

    if options.newline_mode == "single":
        blocks = re.split(r"\n+", trimmed)
    elif options.newline_mode == "double":
        blocks = re.split(r"\n{2,}", trimmed)
    elif options.newline_mode == "none":
        blocks = [re.sub(r"\n+", " ", trimmed)]
    else:
        raise ValueError(f"Unsupported newline mode: {options.newline_mode}")

    units: list[str] = []
    for block in blocks:
        units.extend(_segment_text(block, options))
    return units


def _extract_epub_to_txt(epub_path: Path, options: ParserOptions) -> tuple[Path, Path | None]:
    book = epub.read_epub(str(epub_path), options={"ignore_ncx": False})
    toc_lookup = _build_toc_lookup(book)

    cover_bytes = _extract_cover_image(epub_path)
    cover_path: Path | None = None
    if cover_bytes is not None:
        try:
            image = Image.open(BytesIO(cover_bytes))
            cover_path = epub_path.with_suffix(".png")
            image.save(cover_path)
        except Exception:  # noqa: BLE001
            cover_path = None

    spine_ids = [
        spine_id
        for spine_id, linear in book.spine
        if str(linear).strip().lower() != "no"
    ]
    if not spine_ids:
        spine_ids = [spine_id for spine_id, _ in book.spine]

    items = {
        item.get_id(): item
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    }

    chapter_blocks: list[tuple[str, int, list[str]]] = []
    for spine_id in spine_ids:
        item = items.get(spine_id)
        if item is None:
            continue

        soup = BeautifulSoup(item.get_content(), "lxml-xml")
        item_ref = _normalize_href(getattr(item, "file_name", None) or item.get_name())
        toc_entry = toc_lookup.get(item_ref) or toc_lookup.get(Path(item_ref).name.lower())
        toc_title = str((toc_entry or {}).get("title") or "").strip()
        toc_level = max(1, int((toc_entry or {}).get("level") or 1))

        for anchor in soup.find_all("a", href=True):
            if not any(char.isalpha() for char in anchor.text):
                anchor.extract()
        for superscript in soup.find_all("sup"):
            if superscript.text.isdigit():
                superscript.extract()
        for marker in soup.find_all(class_=re.compile(r"pagebreak|page-break", flags=re.I)):
            marker.extract()

        raw_text = soup.get_text(strip=False)
        fallback_title = _best_title_from_html(
            soup,
            spine_id,
            raw_text,
            mode=options.title_mode,
        )
        if toc_title:
            fallback_title = toc_title

        segments = _extract_segments_from_html(
            soup,
            fallback_title=fallback_title,
            fallback_level=toc_level,
            options=options,
        )
        for title, level, paragraph_units in segments:
            if paragraph_units:
                chapter_blocks.append((title, level, paragraph_units))

    txt_path = epub_path.with_suffix(".txt")
    title_meta = book.get_metadata("DC", "title")
    author_meta = book.get_metadata("DC", "creator")
    book_title = title_meta[0][0] if title_meta and title_meta[0] else epub_path.stem
    book_author = author_meta[0][0] if author_meta and author_meta[0] else "Unknown"

    with txt_path.open("w", encoding="utf-8") as handle:
        handle.write(f"Title: {book_title}\n")
        handle.write(f"Author: {book_author}\n\n")
        handle.write("# Title\n")
        handle.write(f"{book_title}, by {book_author}\n\n")

        for index, (chapter_title, level, units) in enumerate(chapter_blocks, start=1):
            heading = chapter_title or f"Part {index}"
            heading_level = max(1, min(6, int(level)))
            handle.write(f"{'#' * heading_level} {heading}\n\n")
            for unit in units:
                handle.write(f"{unit}\n\n")

    return txt_path, cover_path


def parse_text_book(text_path: Path, options: ParserOptions | None = None) -> BookData:
    active_options = options or ParserOptions()

    book_title = text_path.stem
    book_author = "Unknown"

    chapters: list[ChapterData] = []
    current_title: str | None = None
    current_units: list[str] = []
    current_level = 1

    with text_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("Title: "):
                book_title = line.replace("Title: ", "", 1).strip() or book_title
                continue
            if line.startswith("Author: "):
                book_author = line.replace("Author: ", "", 1).strip() or book_author
                continue

            if line.startswith("#"):
                if current_units:
                    title = current_title or f"Chapter {len(chapters) + 1}"
                    chapters.append(
                        ChapterData(
                            index=len(chapters) + 1,
                            title=title,
                            paragraphs=current_units,
                            level=current_level,
                        )
                    )
                level = len(line) - len(line.lstrip("#"))
                current_level = max(1, level)
                current_title = line.lstrip("#").strip() or f"Chapter {len(chapters) + 1}"
                current_units = []
                continue

            current_units.extend(_segment_text(line, active_options))

    if current_units:
        title = current_title or f"Chapter {len(chapters) + 1}"
        chapters.append(
            ChapterData(
                index=len(chapters) + 1,
                title=title,
                paragraphs=current_units,
                level=current_level,
            )
        )

    if not chapters:
        chapters.append(ChapterData(index=1, title="Chapter 1", paragraphs=[], level=1))

    return BookData(title=book_title, author=book_author, chapters=chapters)


def prepare_text_source(
    source_path: Path,
    source_kind: str,
    append_log: Callable[[str], None] | None = None,
    options: ParserOptions | None = None,
) -> PreparedTextSource:
    active_options = options or ParserOptions()

    if active_options.newline_mode not in SUPPORTED_NEWLINE_MODES:
        raise ValueError(
            f"Unsupported parser newline mode '{active_options.newline_mode}'. "
            f"Valid values: {', '.join(sorted(SUPPORTED_NEWLINE_MODES))}"
        )
    if active_options.title_mode not in SUPPORTED_TITLE_MODES:
        raise ValueError(
            f"Unsupported parser title mode '{active_options.title_mode}'. "
            f"Valid values: {', '.join(sorted(SUPPORTED_TITLE_MODES))}"
        )

    kind = source_kind.lower().strip()
    active_source = source_path
    auto_cover: Path | None = None

    if kind == "epub":
        if append_log:
            append_log("Extracting EPUB into normalized text source.")
        active_source, auto_cover = _extract_epub_to_txt(source_path, active_options)
    elif kind != "txt":
        raise ValueError(f"Unsupported source kind: {source_kind}")

    if append_log:
        append_log(f"Parsing text source: {active_source.name}")

    book = parse_text_book(active_source, active_options)

    if append_log:
        append_log(f"Detected {book.chapter_total} chapters and {book.paragraph_total} text units.")

    return PreparedTextSource(
        text_path=active_source,
        book=book,
        auto_cover_path=auto_cover,
    )
