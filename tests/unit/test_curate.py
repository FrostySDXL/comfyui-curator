"""Smoke tests for curate.py CLI entrypoint."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from curate import main


class TestCurateCLI:
    """Basic smoke tests for the CLI entrypoint."""

    @patch("curate.VisionClient")
    @patch("curate.score_images")
    @patch("curate.find_images")
    @patch("curate.RunStorage")
    def test_dry_run_no_images(
        self,
        mock_storage,
        mock_find,
        mock_score,
        mock_client,
        capsys,
        monkeypatch,
    ):
        """Dry run with no images prints message and exits cleanly."""
        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--dry-run",
                "--batch",
                "test",
                "--prompt",
                "test prompt",
                "--model",
                "test-model",
            ],
        )
        mock_find.return_value = []
        mock_storage.return_value = MagicMock()

        try:
            main()
        except SystemExit as e:
            assert e.code == 0
        captured = capsys.readouterr()
        assert "Dry run" in captured.out or "Dry run" in captured.err

    @patch("sys.exit")
    def test_rejects_batch_with_path_separator(self, mock_exit, monkeypatch):
        """--batch with path separators exits with error."""
        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--batch",
                "../escape",
                "--prompt",
                "test",
                "--model",
                "test-model",
            ],
        )
        main()
        # parser.error calls sys.exit(2). With sys.exit mocked, multiple
        # parser.error calls may stack; check at least one exit with code 2.
        exit_codes = [call.args[0] for call in mock_exit.call_args_list]
        assert 2 in exit_codes

    @patch("curate.VisionClient")
    @patch("curate.score_images")
    @patch("curate.find_images")
    @patch("curate.RunStorage")
    def test_failed_run_has_completed_at(
        self,
        mock_storage,
        mock_find,
        mock_score,
        mock_client,
        monkeypatch,
    ):
        """Failed runs (no images) include a completed_at timestamp."""
        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--batch",
                "test",
                "--prompt",
                "test prompt",
                "--model",
                "test-model",
            ],
        )
        mock_find.return_value = []
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance

        try:
            main()
        except SystemExit:
            pass

        # Verify save_run was called with a run that has completed_at
        mock_storage_instance.save_run.assert_called_once()
        saved_run = mock_storage_instance.save_run.call_args[0][0]
        assert saved_run.status == "failed"
        assert saved_run.completed_at is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(saved_run.completed_at)
