# CLAUDE.md

## Running code

Always use `uv run` instead of `python3` or `python` directly. Direct python invocation is denied in `.claude/settings.json`.

```bash
uv run daily_agenda.py --preview            # Test without sending
uv run daily_agenda.py --date 2026-02-09    # Specific date
```

## Project structure

Single-file Python script (`daily_agenda.py`) that fetches calendar events from Fastmail via CalDAV and sends a formatted HTML agenda email via SMTP. Dependencies are managed with `uv` (see `pyproject.toml`).
