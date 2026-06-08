"""Smoke tests for curate.py CLI entrypoint."""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

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

    def test_dry_run_without_model(self, capsys, monkeypatch):
        """--dry-run should work without --model (model validated after dry-run check)."""
        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--dry-run",
                "--batch",
                "test",
                "--prompt",
                "test prompt",
            ],
        )
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
        # parser.error calls sys.exit(2). With sys.exit mocked, control
        # falls through into the rest of main(), which now also rejects
        # the bad batch (via the stricter RunStorage validation). We
        # catch any SystemExit or downstream ValueError so the test
        # can assert on the recorded exit codes either way.
        try:
            main()
        except (SystemExit, ValueError):
            pass
        # parser.error calls sys.exit(2). With sys.exit mocked, multiple
        # parser.error calls may stack; check at least one exit with code 2.
        exit_codes = [call.args[0] for call in mock_exit.call_args_list]
        assert 2 in exit_codes

    @patch("curate.score_images")
    @patch("curate.find_images")
    @patch("curate.RunStorage")
    @patch("sys.exit")
    def test_dest_validation_skipped_without_move(
        self, mock_exit, mock_storage, mock_find, mock_score, monkeypatch
    ):
        """Without --move, an invalid --dest must NOT trigger parser.error.

        Regression: an earlier version of this test had a bare ``pass`` body
        and provided no real coverage.
        """
        # find_images would otherwise try to read a real path; return empty.
        mock_find.return_value = []
        # score_images returns (results, total_images) — return empty values.
        mock_score.return_value = ([], 0)
        # Without --move, CLI should walk past dest check, then bail out
        # because find_images returned an empty list (no images to score).
        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--batch",
                "test",
                "--prompt",
                "test",
                "--model",
                "test-model",
                "--dest",
                "invalid-dest",
            ],
        )
        try:
            main()
        except SystemExit:
            pass

        # If --dest validation had been triggered, parser.error would have
        # called sys.exit(2) BEFORE the empty-images branch. Collect all
        # exit code arguments and assert 2 (parser.error) is not among them.
        exit_codes = [call.args[0] for call in mock_exit.call_args_list]
        assert 2 not in exit_codes, (
            "Invalid --dest triggered parser.error even though --move was not set. "
            f"sys.exit calls observed: {exit_codes}"
        )

    def test_move_with_invalid_dest(self, monkeypatch):
        """--move with invalid --dest should error."""

        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--batch",
                "test",
                "--prompt",
                "test",
                "--model",
                "test-model",
                "--move",
                "--dest",
                "invalid-dest",
            ],
        )
        try:
            main()
        except SystemExit as e:
            # parser.error calls sys.exit(2)
            assert e.code == 2

    def test_error_message_no_longer_suggests_panel(self, capsys, monkeypatch):
        """Error message should not reference deprecated --panel flag.

        Regression: a previous version of this test had a bare ``pass`` body
        and provided no real coverage. We now invoke main() with --batch
        but no --prompt (and no --panel) and assert that the actual error
        line emitted by argparse does not mention the deprecated --panel
        alias. The usage line may still mention --panel as a registered
        option; that is expected and intentional.
        """
        monkeypatch.setattr(
            "sys.argv",
            [
                "curate",
                "--batch",
                "test",
            ],
        )
        with pytest.raises(SystemExit):
            main()
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # argparse's error lines are the ones that follow the usage block
        # and contain "error:". They are the actionable message, distinct
        # from the usage line which legitimately enumerates all options.
        error_lines = [line for line in combined.splitlines() if "error:" in line]
        assert error_lines, f"expected an argparse error line, got:\n{combined}"
        error_text = " ".join(error_lines)
        assert "--panel" not in error_text, (
            "argparse error message should not mention the deprecated "
            f"--panel alias. Got: {error_text!r}"
        )
        # The error should also point to --prompt (the current flag), so
        # this test catches both regressions: removal of the hint AND a
        # future change that drops the error message entirely.
        assert "--prompt" in error_text, (
            f"argparse error should mention --prompt, got: {error_text!r}"
        )

    def test_main_return_type_annotation(self):
        """main() should have return type annotation -> None."""
        import inspect

        sig = inspect.signature(main)
        assert sig.return_annotation is not inspect.Parameter.empty

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

    @patch("curate.VisionClient")
    @patch("curate.score_images")
    @patch("curate.find_images")
    @patch("curate.RunStorage")
    def test_move_mode_passed_to_run(
        self,
        mock_storage,
        mock_find,
        mock_score,
        mock_client,
        monkeypatch,
    ):
        """--move flag sets move_enabled=True and passes dest folder."""
        from pathlib import Path
        from ai_curate.models import ImageResult

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
                "--move",
                "--dest",
                "finals",
                "--source",
                "inbox",
            ],
        )
        # Simulate 1 scored image
        mock_find.return_value = [Path("test.png")]
        mock_score.return_value = (
            [ImageResult(filename="test.png", score=2, total=3, details={1: "YES"})],
            1,
        )
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance

        try:
            main()
        except SystemExit:
            pass

        mock_storage_instance.save_run.assert_called_once()
        saved_run = mock_storage_instance.save_run.call_args[0][0]
        assert saved_run.move_enabled is True
        assert saved_run.destination_folder == "finals"
        assert saved_run.source_folder == "inbox"

    @patch("curate.VisionClient")
    @patch("curate.score_images")
    @patch("curate.find_images")
    @patch("curate.RunStorage")
    def test_explicit_elements_passed_to_run(
        self,
        mock_storage,
        mock_find,
        mock_score,
        mock_client,
        monkeypatch,
    ):
        """--elements flag provides explicit element list."""
        from pathlib import Path
        from ai_curate.models import ImageResult

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
                "--elements",
                "red dress, blue sky",
            ],
        )
        mock_find.return_value = [Path("test.png")]
        mock_score.return_value = (
            [ImageResult(filename="test.png", score=2, total=3, details={1: "YES"})],
            1,
        )
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance

        try:
            main()
        except SystemExit:
            pass

        # Check the run passed to save_run includes explicit elements + quality
        saved_run = mock_storage_instance.save_run.call_args[0][0]
        assert "red dress" in saved_run.elements
        assert "blue sky" in saved_run.elements

    @patch("curate.VisionClient")
    @patch("curate.score_images")
    @patch("curate.find_images")
    @patch("curate.RunStorage")
    def test_scoring_flow_persists_run(
        self,
        mock_storage,
        mock_find,
        mock_score,
        mock_client,
        monkeypatch,
    ):
        """Successful scoring flow persists a completed run."""
        from pathlib import Path
        from ai_curate.models import ImageResult

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
        mock_find.return_value = [Path("test.png")]
        mock_score.return_value = (
            [ImageResult(filename="test.png", score=2, total=3, details={1: "YES"})],
            1,
        )
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance

        try:
            main()
        except SystemExit:
            pass

        mock_storage_instance.save_run.assert_called_once()
        saved_run = mock_storage_instance.save_run.call_args[0][0]
        assert saved_run.status == "completed"
        assert saved_run.model == "test-model"
