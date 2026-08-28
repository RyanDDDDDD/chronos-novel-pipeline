from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect


def test_migrate_all_stamps_every_novel_db(tmp_path, monkeypatch):
    novels = tmp_path / "novels"
    (novels / "n1").mkdir(parents=True)
    (novels / "n2").mkdir(parents=True)
    for n in ("n1", "n2"):
        create_engine(f"sqlite:///{novels / n / 'chronos.sqlite3'}").connect().close()
    env = os.environ.copy()
    env["CHRONOS_NOVELS_DIR"] = str(novels)
    r = subprocess.run(
        [sys.executable, "scripts/migrate_db.py", "--all"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, r.stderr
    for n in ("n1", "n2"):
        insp = inspect(create_engine(f"sqlite:///{novels / n / 'chronos.sqlite3'}"))
        assert "alembic_version" in insp.get_table_names()
