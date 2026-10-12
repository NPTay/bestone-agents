import sys


def use_utf8_console() -> None:
    """Windows consoles may be cp1252; force UTF-8 so Vietnamese text prints."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
