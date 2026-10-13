from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import orm

from app.content.pictures import (
    choose_pictures,
    list_pictures,
    parse_projects,
    record_use,
)

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)

KB = """# KB

## 13. Công trình trong thư viện ảnh

### Thư mục: a
- Tên hiển thị: Tòa nhà A
- Năm: 2020

### Thư mục: b
- Tên hiển thị: [GĐ BỔ SUNG]
- Năm: [GĐ BỔ SUNG]
"""


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


def _tree(tmp_path: Path, files: list[str], exclude: str = "") -> tuple[Path, Path]:
    pic = tmp_path / "Picture"
    pic.mkdir()
    for f in files:
        _touch(pic, f)
    ex = tmp_path / "exclude.txt"
    ex.write_text(exclude, encoding="utf-8")
    return pic, ex


def test_list_pictures_filters_types_and_excludes(tmp_path: Path) -> None:
    pic, ex = _tree(tmp_path, ["a/1.jpg", "a/2.PNG", "a/v.mp4", "b/3.jpg"], "# c\nb\n")
    assert list_pictures(pic, ex) == {"a": ["a/1.jpg", "a/2.PNG"]}


def test_list_pictures_root_files_and_file_exclude(tmp_path: Path) -> None:
    pic, ex = _tree(tmp_path, ["r1.jpg", "r2.jpeg", "a/1.jpg"], "a/1.jpg\n")
    assert list_pictures(pic, ex) == {"": ["r1.jpg", "r2.jpeg"]}


def test_parse_projects_verified_flag() -> None:
    projects = parse_projects(KB)
    assert projects["a"].verified is True
    assert "Tòa nhà A" in projects["a"].text
    assert projects["b"].verified is False


def test_choose_prefers_least_used_folder_and_files(
    db: orm.Session, tmp_path: Path
) -> None:
    pic, ex = _tree(tmp_path, ["a/1.jpg", "a/2.jpg", "b/3.jpg"])
    first = choose_pictures(db, pic, ex, KB)
    assert first is not None and first.folder == "a"
    record_use(db, ["a/1.jpg"], NOW)
    second = choose_pictures(db, pic, ex, KB)
    assert second is not None and second.folder == "b"
    record_use(db, ["b/3.jpg"], NOW)
    third = choose_pictures(db, pic, ex, KB)
    assert third is not None and third.folder == "a"
    assert third.paths == ["a/2.jpg", "a/1.jpg"]
    record_use(db, ["a/1.jpg"], NOW)  # existing row increments
    assert choose_pictures(db, pic, ex, KB, max_images=1) is not None


def test_choose_does_not_record_usage(db: orm.Session, tmp_path: Path) -> None:
    pic, ex = _tree(tmp_path, ["a/1.jpg"])
    choose_pictures(db, pic, ex, KB)
    again = choose_pictures(db, pic, ex, KB)
    assert again is not None and again.folder == "a"


def test_choice_project_only_when_verified(db: orm.Session, tmp_path: Path) -> None:
    pic, ex = _tree(tmp_path, ["a/1.jpg", "b/2.jpg"])
    a = choose_pictures(db, pic, ex, KB)
    assert a is not None and a.folder == "a" and a.project is not None
    record_use(db, ["a/1.jpg"], NOW)
    b = choose_pictures(db, pic, ex, KB)
    assert b is not None and b.folder == "b" and b.project is None


def test_choose_returns_none_when_library_empty(
    db: orm.Session, tmp_path: Path
) -> None:
    pic, ex = _tree(tmp_path, [])
    assert choose_pictures(db, pic, ex, KB) is None
