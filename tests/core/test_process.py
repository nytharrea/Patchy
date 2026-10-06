import sys

import pytest

from patchy.core import process


def test_clean_env_keeps_only_the_safe_keys():
    source = {"PATH": "/usr/bin", "HOME": "/home/runner", "GITHUB_TOKEN": "secret", "KS_PASSWORD": "secret"}
    assert process.clean_env(environ=source) == {"PATH": "/usr/bin", "HOME": "/home/runner"}


def test_clean_env_adds_explicit_extras_on_top():
    env = process.clean_env({"PATCHY_KS_PASSWORD": "x"}, environ={"PATH": "/usr/bin", "OTHER": "y"})
    assert env == {"PATH": "/usr/bin", "PATCHY_KS_PASSWORD": "x"}


def test_clean_env_reads_the_real_environment_by_default(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("JAVA_HOME", "/opt/java")
    env = process.clean_env()
    assert env.get("JAVA_HOME") == "/opt/java"
    assert "GITHUB_TOKEN" not in env


async def test_run_capture_returns_output_and_exit_code():
    result = await process.run_capture([sys.executable, "-c", "print('hello'); raise SystemExit(3)"], timeout=10)
    assert result.returncode == 3
    assert result.output.strip() == "hello"


async def test_run_capture_merges_stderr_into_output_by_default():
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    result = await process.run_capture([sys.executable, "-c", code], timeout=10)
    assert "out" in result.output and "err" in result.output
    assert result.error == ""


async def test_run_capture_can_keep_stderr_separate():
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    result = await process.run_capture([sys.executable, "-c", code], timeout=10, stderr_to_stdout=False)
    assert result.output.strip() == "out"
    assert result.error.strip() == "err"


async def test_run_capture_gives_the_child_only_the_environment_it_is_handed(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    code = "import os; print(os.environ.get('GITHUB_TOKEN', 'absent'), os.environ.get('EXTRA', 'absent'))"
    result = await process.run_capture([sys.executable, "-c", code], timeout=10)
    assert result.output.split() == ["absent", "absent"]

    result = await process.run_capture(
        [sys.executable, "-c", code], timeout=10, env=process.clean_env({"EXTRA": "yes"})
    )
    assert result.output.split() == ["absent", "yes"]


async def test_run_capture_kills_a_process_that_overruns_its_timeout():
    with pytest.raises(process.ProcessTimeout, match="did not finish within"):
        await process.run_capture([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)
