import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SCRIPTS = ["entrypoint.sh", "backup.sh", "bootstrap.sh"]


def _compose() -> dict[str, Any]:
    text = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    return data


def _env_names() -> set[str]:
    names = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if m:
            names.add(m.group(1))
    return names


def test_services_and_ports() -> None:
    services = _compose()["services"]
    assert set(services) == {"app", "db", "caddy"}
    assert [n for n, s in services.items() if "ports" in s] == ["caddy"]
    assert services["db"]["image"].startswith("postgres:16")
    assert services["app"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["app"]["restart"] == "unless-stopped"
    assert services["caddy"]["networks"]["default"]["ipv4_address"] == "172.28.0.10"


def test_network_subnet() -> None:
    cfg = _compose()["networks"]["default"]["ipam"]["config"]
    assert cfg[0]["subnet"] == "172.28.0.0/24"


def test_referenced_variables_exist_in_env_example() -> None:
    text = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    text += (DEPLOY / "entrypoint.sh").read_text(encoding="utf-8")
    text += (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    refs = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", text)) | set(
        re.findall(r"\$([A-Z][A-Z0-9_]+)", text)
    )
    assert refs
    assert refs <= _env_names(), refs - _env_names()


def test_env_example_has_no_secret_values() -> None:
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if m and re.search(r"(_KEY|_TOKEN|_SECRET|_PASSWORD)$", m.group(1)):
            assert m.group(2) == "", m.group(1)


def test_env_example_has_database_url_name() -> None:
    assert "DATABASE_URL" in (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DATABASE_URL" in _compose()["services"]["app"]["environment"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_lf_and_syntax(name: str) -> None:
    path = DEPLOY / name
    assert b"\r\n" not in path.read_bytes()
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_entrypoint_command() -> None:
    text = (DEPLOY / "entrypoint.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in text
    assert "--proxy-headers" in text and '"$TRUSTED_PROXY_IPS"' in text


def test_test_override_binds_db_to_localhost_only() -> None:
    text = (DEPLOY / "docker-compose.test.yml").read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    assert data["services"]["db"]["ports"] == ["127.0.0.1:5432:5432"]


def test_compose_name_and_ip_range() -> None:
    data = _compose()
    assert data["name"] == "bestone"
    cfg = data["networks"]["default"]["ipam"]["config"][0]
    assert cfg["ip_range"] == "172.28.0.128/25"


def test_bootstrap_fixes_ownership_and_timezone() -> None:
    text = (DEPLOY / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'chown "$OWNER:$OWNER" .env' in text
    assert "timedatectl set-timezone Asia/Ho_Chi_Minh" in text
    assert "usermod -aG docker" in text
