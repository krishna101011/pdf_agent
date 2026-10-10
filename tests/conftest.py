import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    ws, data = tmp_path / "workspace", tmp_path / "data"
    ws.mkdir()
    data.mkdir()
    return Settings(api_key="xai-test-key-1234567890abcdef", workspace=ws, data_dir=data,
                    delay_seconds=0.0, max_steps=5, github_token="ghp_" + "a" * 30,
                    vercel_token="vercel_token_12345678", smtp_user="me@example.com",
                    smtp_password="app-password-1234")


@pytest.fixture
def make_pdf(tmp_path):
    def _make(pages=("Page one: a block slides down a ramp.", "Page two: Solved example 3.2, find the speed."),
              name="book.pdf"):
        import pymupdf
        doc = pymupdf.open()
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), text)
        path = tmp_path / name
        doc.save(path)
        doc.close()
        return path
    return _make
