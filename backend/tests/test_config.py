from pathlib import Path

from nifty.config import ENV_FILE, Settings


def test_env_file_is_repo_root() -> None:
    assert ENV_FILE.parent == Path(__file__).resolve().parents[2]


def test_settings_read_env_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    f = tmp_path / "e.env"
    f.write_text("POSTGRES_DB=from_file\n")
    s = Settings(_env_file=f)  # type: ignore[call-arg]
    assert s.postgres_db == "from_file"
