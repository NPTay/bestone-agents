"""Picture library rotation (afternoon posts) and project info from the KB."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PictureUse

PICTURE_SUFFIXES = {".jpg", ".jpeg", ".png"}
UNVERIFIED_MARKER = "[GĐ BỔ SUNG"
_HEADING_RE = re.compile(r"^###\s+Thư mục:\s*(.+?)\s*$", re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^#{1,3}\s", re.MULTILINE)


@dataclass
class ProjectInfo:
    folder: str
    verified: bool
    text: str


@dataclass
class PictureChoice:
    folder: str
    paths: list[str]
    project: ProjectInfo | None


def parse_projects(kb_text: str) -> dict[str, ProjectInfo]:
    """Parse `### Thư mục: <name>` subsections; verified = no placeholder left."""
    projects: dict[str, ProjectInfo] = {}
    for match in _HEADING_RE.finditer(kb_text):
        start = match.end()
        nxt = _NEXT_SECTION_RE.search(kb_text, start)
        body = kb_text[start : nxt.start() if nxt else len(kb_text)].strip()
        folder = match.group(1)
        projects[folder] = ProjectInfo(
            folder=folder, verified=UNVERIFIED_MARKER not in body, text=body
        )
    return projects


def _load_excludes(exclude_file: Path) -> set[str]:
    if not exclude_file.is_file():
        return set()
    out: set[str] = set()
    for line in exclude_file.read_text(encoding="utf-8").splitlines():
        line = line.strip().replace("\\", "/").strip("/")
        if line and not line.startswith("#"):
            out.add(line)
    return out


def list_pictures(picture_dir: Path, exclude_file: Path) -> dict[str, list[str]]:
    """Map folder ("" for root) to sorted relative image paths, minus excludes."""
    excludes = _load_excludes(exclude_file)
    result: dict[str, list[str]] = {}
    if not picture_dir.is_dir():
        return result
    for file in picture_dir.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in PICTURE_SUFFIXES:
            continue
        rel = file.relative_to(picture_dir).as_posix()
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        parts = rel.split("/")
        prefixes = {"/".join(parts[: i + 1]) for i in range(len(parts))}
        if prefixes & excludes:
            continue
        result.setdefault(folder, []).append(rel)
    return {folder: sorted(paths) for folder, paths in sorted(result.items())}


def choose_pictures(
    db: Session,
    picture_dir: Path,
    exclude_file: Path,
    kb_text: str,
    max_images: int = 3,
) -> PictureChoice | None:
    """Pick the least-used folder, then its least-used files. Records nothing."""
    library = list_pictures(picture_dir, exclude_file)
    if not library:
        return None
    counts = {
        row.path: row.used_count for row in db.scalars(select(PictureUse)).all()
    }

    def folder_total(folder: str) -> int:
        return sum(counts.get(p, 0) for p in library[folder])

    folder = min(library, key=lambda f: (folder_total(f), f))
    paths = sorted(library[folder], key=lambda p: (counts.get(p, 0), p))[:max_images]
    project = parse_projects(kb_text).get(folder)
    if project is not None and not project.verified:
        project = None
    return PictureChoice(folder=folder, paths=paths, project=project)


def record_use(db: Session, paths: list[str], now: datetime) -> None:
    """Increment usage for each relative path, creating rows as needed."""
    for path in paths:
        row = db.scalar(select(PictureUse).where(PictureUse.path == path))
        if row is None:
            row = PictureUse(path=path, used_count=0)
            db.add(row)
        row.used_count += 1
        row.last_used_at = now
    db.commit()
