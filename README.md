# ebook2m4b

Modernized EPUB/TXT to M4B pipeline with Docker Compose, FastAPI + HTMX UI, and background worker progress.

## What this folder provides

- Nvidia-only runtime (CUDA)
- Docker Compose stack with explicit project name
- Shared persistent host folder mapped as /data in containers
- Web UI on port 7777
- Parse-first workflow: parse chapters, verify selection, then generate M4B
- Pluggable TTS providers: Kokoro and Edge TTS
- Optional existing-file mode for sources already under /data
- CLI compatibility path in the same codebase

## Data layout

Everything lives under the host folder ebook2m4b/data and is visible on disk:

- data/inputs: uploaded or source files
- data/work: per-job working directory
- data/results: final outputs and selected artifacts
- data/ebook2m4b.db: job/progress database

## Run

```bash
cd ebook2m4b
docker compose -f compose.yaml up --build
```

Optional for WSL + docker.exe environments with distro mount issues:

```bash
EBOOK2M4B_DATA_HOST_PATH=/mnt/c/Users/Public/ebook2m4b-data docker.exe compose -f compose.yaml up --build
```

Open:

- http://localhost:7777

## Local development with uv

```bash
uv sync
uv run python -m ebook2m4b.web_ui.app
```

## Use the web UI

1. Upload an EPUB/TXT file or select an existing one from /data
2. Optionally paste a text chunk directly in the form instead of uploading
2. Pick an engine and speaker (speaker metadata shows language, gender, and quality)
3. Set speed/options (saved for generation phase)
4. If you choose Edge TTS, optionally filter locale and tune rate/volume/pitch
5. Parse chapters
6. Review the parsed chapter checklist (hierarchy preserved when available) and keep or adjust selections
7. Generate selected chapters
8. Watch both progress bars:
	- Overall progress (entire run)
	- Current stage progress (active stage)
	You also get chapter and text-unit counters during synthesis.
9. Expand Details on any job card for inline metadata and quick diagnostics
10. Download M4B when complete and use the inline audio player to preview playback in the UI

If live Edge voice discovery fails (network/transient errors), the app automatically falls back to a full static voice catalog so you can still select voices.

## Place source files directly in data

You can also copy files into data/inputs manually and select them from the UI.

## CLI (inside container)

```bash
docker compose -f compose.yaml run --rm web python -m ebook2m4b.cli inputs/mybook.epub --speaker af_heart
```

The command reads from /data and writes outputs to /data/results/cli.

## Tests (reusable scripts)

Run the reusable pytest suite from the workspace root:

```bash
uv run --extra dev pytest tests -q
```

Targeted examples:

```bash
uv run --extra dev pytest tests/test_parser_chapter_levels.py -q
uv run --extra dev pytest tests/test_edge_fallback_catalog.py -q
uv run --extra dev pytest tests/test_parse_generate_split.py -q
```
