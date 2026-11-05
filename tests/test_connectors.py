import pytest
from pydantic import ValidationError

from unclog.cli import main
from unclog.connectors import FileDropConnector, WriteAction, available, pull
from unclog.store import ClientStore


def test_file_drop_lists_supported_files(upload_dir):
    c = FileDropConnector(upload_dir)
    names = [d.name for d in c.list_datasets()]
    assert "crm/leads.csv" in names and "deck.pptx" not in names and ".DS_Store" not in names
    assert c.unsupported() == ["deck.pptx"]


def test_file_drop_blocks_path_traversal(upload_dir, tmp_path):
    (tmp_path / "secret.csv").write_text("a\n1\n")
    with pytest.raises(FileNotFoundError):
        FileDropConnector(upload_dir).fetch("../secret.csv")


def test_pull_end_to_end(upload_dir, tmp_path):
    store = ClientStore(tmp_path / "clients", "acme")
    report = pull(FileDropConnector(upload_dir), store, actor="intake")
    assert len(report.ingested) == 7 and not report.failed
    assert report.skipped_unsupported == ["deck.pptx"]
    assert report.pii_redactions > 0
    assert len(store.list_sources()) == 7
    assert len(list((store.root / "raw").iterdir())) == 7
    again = pull(FileDropConnector(upload_dir), store, actor="intake")
    assert len(again.duplicates) == 7 and not again.ingested


def test_pull_reports_bad_file_and_continues(upload_dir, tmp_path):
    (upload_dir / "broken.xlsx").write_bytes(b"not a zip")
    report = pull(FileDropConnector(upload_dir), ClientStore(tmp_path, "acme"), actor="intake")
    assert "broken.xlsx" in report.failed and len(report.ingested) == 7


def test_write_actions_are_draft_by_default():
    a = WriteAction(
        connector="google_ads",
        operation="create_ad",
        payload={},
        change_summary="Add 5 paused variants of top ad",
    )
    assert a.draft
    with pytest.raises(ValidationError, match="approval_ref"):
        WriteAction(
            connector="google_ads",
            operation="create_ad",
            payload={},
            draft=False,
            change_summary="Add 5 live variants of top ad",
        )


def test_file_drop_is_read_only(upload_dir):
    c = FileDropConnector(upload_dir)
    with pytest.raises(NotImplementedError):
        c.write(
            WriteAction(
                connector="file_drop",
                operation="x",
                payload={},
                change_summary="should not be possible",
            )
        )
    assert "file_drop" in available()


def test_cli_ingest_and_list(upload_dir, tmp_path, capsys):
    root = str(tmp_path / "clients")
    assert main(["--clients-root", root, "ingest", "acme", str(upload_dir)]) == 0
    assert main(["--clients-root", root, "sources", "acme"]) == 0
    out = capsys.readouterr().out
    assert "event_log" in out and "interview_coo.vtt" in out
