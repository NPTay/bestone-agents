from pathlib import Path

from sqlalchemy import Engine

from app.config import get_settings
from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base


def init_db(engine: Engine) -> None:
    """Create the data directories and all tables."""
    data_dir = Path(get_settings().DATA_DIR)
    for sub in (data_dir, data_dir / "media", data_dir / "logs"):
        sub.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
