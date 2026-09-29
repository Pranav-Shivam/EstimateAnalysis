import os
import subprocess
import sys
from pathlib import Path

from core.config.settings import Settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_worker.py"


def test_run_worker_imports_the_app_when_started_as_a_script_from_another_directory(tmp_path):
    # pytest puts backend/ on sys.path for every test, so only a separate interpreter shows whether the script
    # can find the `app` package on its own. run_name keeps main() from starting a real worker. Settings come
    # from the environment because there is no .env in tmp_path.
    settings = Settings()
    env = {
        **os.environ, "DATABASE_URL": settings.database_url, "OPENAI_API_KEY": settings.openai_api_key,
        "ANTHROPIC_API_KEY": settings.anthropic_api_key,
    }
    result = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(SCRIPT)!r}, run_name='imported')"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
