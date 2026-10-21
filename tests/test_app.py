"""Streamlit UI: startup, missing credentials, success/partial/error rendering, real server boot."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from core.briefing import BriefingError
from test_report import make_briefing

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app(monkeypatch, no_env_file):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def start(result=None):
        async def fake_generate(query, progress):
            progress("step")
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr("core.briefing.generate_briefing", fake_generate)
        return AppTest.from_file(APP, default_timeout=30).run()

    return start


def submit(at: AppTest, text="NSCLC") -> AppTest:
    at.text_input[0].set_value(text)
    at.button[0].click()
    return at.run()


def test_missing_key_disables_generation(monkeypatch, no_env_file):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert "OPENAI_API_KEY missing" in at.sidebar.error[0].value
    assert at.button[0].disabled


def test_success_renders_all_sections(app):
    at = submit(app(make_briefing()))
    assert not at.exception and not at.error
    assert [t.label for t in at.tabs][:4] == ["Executive summary", "Standard of care", "Emerging treatments & trials (1)", "Companies & institutions"]
    assert not at.warning  # no partial banner


def test_partial_briefing_shows_warning_banner(app):
    at = submit(app(make_briefing(source_failures=["openfda timed out"])))
    assert "Partial briefing" in at.warning[0].value


def test_errors_are_shown_and_stale_briefing_cleared(app, monkeypatch):
    at = submit(app(make_briefing()))
    assert "briefing" in at.session_state

    async def fail(query, progress):
        raise BriefingError("The research sources could not be reached")
    monkeypatch.setattr("core.briefing.generate_briefing", fail)
    at = submit(at)
    assert at.error[0].value == "The research sources could not be reached"
    assert "briefing" not in at.session_state and not at.tabs


def test_unexpected_exception_does_not_crash_app(app):
    at = submit(app(RuntimeError("boom")))
    assert "Something went wrong" in at.error[0].value


def test_streamlit_server_starts():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", APP, "--server.headless", "true", "--server.port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/_stcore/health", timeout=2).text == "ok":
                    return
            except httpx.HTTPError:
                time.sleep(0.5)
        pytest.fail("Streamlit server did not become healthy")
    finally:
        proc.kill()
