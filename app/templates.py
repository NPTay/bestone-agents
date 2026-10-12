from pathlib import Path

from fastapi.templating import Jinja2Templates

# Autoescape is on by default for .html templates.
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
