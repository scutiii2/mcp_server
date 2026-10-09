"""Run the actual batch flow with a stand-in builder that produces artifacts."""

import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows batch build")
@pytest.mark.parametrize("build_exit", [0, 1], ids=["success", "failure"])
def test_build_cleans_only_successful_pyinstaller_artifacts(tmp_path, build_exit):
    source = Path(__file__).resolve().parents[1] / "build.bat"
    # CMD needs CALL to return from a .cmd test double; real python.exe
    # returns directly. Keep all builder/cleanup control flow unchanged.
    (tmp_path / "build.bat").write_text(source.read_text().replace("python -m", "call python -m"))
    scripts = tmp_path / ".venv_launcher" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").touch()
    (scripts / "activate.bat").write_text("@echo off\nexit /b 0\n")
    (tmp_path / "python.cmd").write_text(
        '@echo off\n'
        'if "%2"=="PyInstaller" (\n'
        '  mkdir build\\pyinstaller\n'
        '  echo cache>build\\pyinstaller\\cache.txt\n'
        '  echo spec>build\\scuti_server_launcher.spec\n'
        '  mkdir dist\n'
        '  echo exe>dist\\scuti_server_launcher.exe\n'
        f'  exit /b {build_exit}\n'
        ')\nexit /b 0\n'
    )
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "keep.txt").write_text("unrelated")
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "build.bat"], cwd=tmp_path,
        input="\n", capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
    )
    assert result.returncode == build_exit, result.stdout + result.stderr
    assert (tmp_path / "dist" / "scuti_server_launcher.exe").read_text().strip() == "exe"
    assert (tmp_path / "build" / "keep.txt").read_text() == "unrelated"
    assert (scripts / "python.exe").exists()
    assert (tmp_path / "build" / "pyinstaller").exists() == bool(build_exit)
    assert (tmp_path / "build" / "scuti_server_launcher.spec").exists() == bool(build_exit)
