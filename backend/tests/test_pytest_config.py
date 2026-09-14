"""Guards that the pytest configuration is actually in effect.

CI used to pass `--md-report-output "$GITHUB_STEP_SUMMARY"`. pytest treats an
existing out-of-tree path as a test path argument, so the rootdir became
`/home/runner/work/_temp`, no configuration file was found, and
`asyncio_mode = auto` was lost. Under pytest-asyncio < 1.0 the 47 async tests
were then silently *skipped* while the job stayed green.

These tests fail whenever the configuration is not picked up, so a lost config
can no longer masquerade as a passing suite.
"""

import pytest


def test_asyncio_mode_is_auto(pytestconfig: pytest.Config) -> None:
    """Async tests must run, not be skipped for want of a marker."""
    assert pytestconfig.getini("asyncio_mode") == "auto"


def test_config_file_is_pyproject(pytestconfig: pytest.Config) -> None:
    """Configuration comes from backend/pyproject.toml and nowhere else."""
    config_file = pytestconfig.inipath
    assert config_file is not None, "no pytest configuration file was loaded"
    assert config_file.name == "pyproject.toml"
    assert config_file.parent.name == "backend"


async def test_async_tests_are_collected_and_run() -> None:
    """An unmarked coroutine test only runs when asyncio auto mode is active."""
    assert True
