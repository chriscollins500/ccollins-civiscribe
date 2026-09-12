from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import publish_registry_bundle as publisher


def test_publication_verifies_bundle_before_reading_credentials_or_calling_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verify = Mock(side_effect=ValueError("bad checksum"))
    monkeypatch.setattr(publisher, "verify_bundle", verify)
    monkeypatch.delenv("REGISTRY_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="bad checksum"):
        publisher.publish(tmp_path, "a" * 40, tmp_path / "missing-notes")
    verify.assert_called_once_with(tmp_path, "a" * 40)


def test_publication_errors_never_echo_credentials_or_signed_urls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sensitive = "https://example.test/upload?signature=private-value"
    monkeypatch.setattr(publisher, "publish", Mock(side_effect=RuntimeError(sensitive)))
    monkeypatch.setattr(sys, "argv", ["publish", "--commit", "a" * 40, "--changelog", "notes"])
    assert publisher.main() == 1
    output = capsys.readouterr()
    assert sensitive not in output.err + output.out
    assert "no automatic retry" in output.err
