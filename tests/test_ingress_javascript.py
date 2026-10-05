"""Run the actual embedded UI rendering code when Node is available (CI)."""

from pathlib import Path
import shutil
import subprocess

import pytest

from grobro.ha.battery_ingress import _INDEX_HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="Node required for JavaScript UI checks")
def test_ingress_overview_rendering():
    result = subprocess.run(
        [shutil.which("node"), str(Path(__file__).with_name("ingress_overview.test.cjs"))],
        input=_INDEX_HTML, text=True, encoding="utf-8", capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
