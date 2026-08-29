"""Verify the M3D prompt is present in a built wheel."""

import subprocess
import zipfile
from pathlib import Path


def test_system_prompt_is_included_in_built_wheel(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        prompt_name = "verbaops/agent/prompts/system_v2.txt"
        assert prompt_name in archive.namelist()
        assert len(archive.read(prompt_name)) > 0
