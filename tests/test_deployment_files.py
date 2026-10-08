from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_runs_non_root_with_browser_and_healthcheck():
    content = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim" in content
    assert "playwright install --with-deps chromium" in content
    assert "USER liteclaw" in content
    assert "HEALTHCHECK" in content
    assert 'CMD ["python", "-m", "liteclaw"]' in content


def test_compose_uses_single_service_persistent_volumes_and_required_key():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["liteclaw"]
    assert service["build"] == "."
    assert service["restart"] == "unless-stopped"
    assert "liteclaw-data:/data" in service["volumes"]
    assert "./workspace:/workspace" in service["volumes"]
    assert ":?" in service["environment"]["LITECLAW_SERVER_API_KEY"]
    assert "liteclaw-data" in compose["volumes"]
    assert "deploy" not in service


def test_dockerignore_excludes_secrets_and_local_state():
    patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in patterns
    assert ".git" in patterns
    assert ".venv*" in patterns
    assert "data" in patterns


def test_pgvector_compose_overlay_is_optional_and_persistent():
    overlay = yaml.safe_load(
        (ROOT / "compose.pgvector.yaml").read_text(encoding="utf-8")
    )
    postgres = overlay["services"]["postgres"]
    liteclaw = overlay["services"]["liteclaw"]

    assert postgres["image"] == "pgvector/pgvector:0.8.7-pg17-bookworm"
    assert "postgres-data:/var/lib/postgresql/data" in postgres["volumes"]
    assert "pg_isready" in " ".join(postgres["healthcheck"]["test"])
    assert "postgresql://" in liteclaw["environment"]["LITECLAW_PGVECTOR_URL"]
    assert "postgres" in liteclaw["depends_on"]
    assert "postgres-data" in overlay["volumes"]
