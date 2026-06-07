"""Smoke tests for curate.py CLI entrypoint."""

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
