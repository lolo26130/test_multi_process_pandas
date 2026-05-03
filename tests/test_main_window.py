"""Tests de MainWindow : initialisation, buffer circulaire, états UI."""
import numpy as np
import pytest

from test_multi_process_pandas.main import (
    MainWindow, BUFFER_SIZE, N_CHANNELS, CHANNEL_NAMES,
)


class TestInit:

    def test_title(self, win):
        assert "Dynamic" in win.windowTitle()

    def test_curves_match_channels(self, win):
        """Une courbe pyqtgraph par canal défini dans CHANNEL_NAMES."""
        assert set(win.curves.keys()) == set(CHANNEL_NAMES)

    def test_checkboxes_match_channels(self, win):
        assert set(win.checkboxes.keys()) == set(CHANNEL_NAMES)

    def test_all_checkboxes_checked_by_default(self, win):
        for name, cb in win.checkboxes.items():
            assert cb.isChecked(), f"checkbox '{name}' devrait être cochée"

    def test_watcher_thread_running(self, win):
        assert win.watcher_thread.isRunning()


class TestLogMsg:

    def test_appends_text(self, win):
        win.log_msg("hello test")
        assert "hello test" in win.log.toPlainText()

    def test_converts_to_string(self, win):
        win.log_msg(42)
        assert "42" in win.log.toPlainText()

    def test_multiple_messages(self, win):
        for msg in ("aaa", "bbb", "ccc"):
            win.log_msg(msg)
        text = win.log.toPlainText()
        assert "aaa" in text and "bbb" in text and "ccc" in text


class TestGetViews:

    def test_empty_buffer_returns_none(self, win):
        """Aucune donnée → (None, None)."""
        v1, v2 = win.get_views()
        assert v1 is None and v2 is None

    def test_partial_buffer(self, win):
        """Buffer partiellement rempli → (df[:n], None), données correctes."""
        n = 10
        t0 = 1_700_000_000.0
        for i in range(n):
            win.data[i, 0] = t0 + i
            win.data[i, 1:] = float(i)
        win.meta[0] = n

        v1, v2 = win.get_views()

        assert v2 is None
        assert len(v1) == n
        assert v1["t"].iloc[0] == pytest.approx(t0)
        assert v1["t"].iloc[-1] == pytest.approx(t0 + n - 1)

    def test_full_buffer_two_views(self, win):
        """Buffer plein → deux vues, ensemble = BUFFER_SIZE lignes."""
        t0 = 1_700_000_000.0
        for i in range(BUFFER_SIZE):
            win.data[i, 0] = t0 + i
            win.data[i, 1:] = float(i)

        extra = 7
        for i in range(extra):
            pos = i          # pos = (BUFFER_SIZE + i) % BUFFER_SIZE = i
            win.data[pos, 0] = t0 + BUFFER_SIZE + i
            win.data[pos, 1:] = float(BUFFER_SIZE + i)
        win.meta[0] = BUFFER_SIZE + extra

        v1, v2 = win.get_views()

        assert v1 is not None and v2 is not None
        assert len(v1) + len(v2) == BUFFER_SIZE

    def test_full_buffer_chronological_order(self, win):
        """Après concaténation v1+v2, les timestamps sont croissants."""
        t0 = 1_700_000_000.0
        for i in range(BUFFER_SIZE):
            win.data[i, 0] = t0 + i
            win.data[i, 1:] = float(i)

        extra = 7
        for i in range(extra):
            win.data[i, 0] = t0 + BUFFER_SIZE + i
            win.data[i, 1:] = float(BUFFER_SIZE + i)
        win.meta[0] = BUFFER_SIZE + extra

        v1, v2 = win.get_views()
        t_all = np.concatenate((v1["t"].values, v2["t"].values))

        assert np.all(np.diff(t_all) > 0), "Timestamps non monotones après concaténation"


class TestUIState:

    def test_uncheck_hides_curve(self, win, qtbot):
        """Décocher une checkbox masque la courbe correspondante."""
        win.checkboxes["ch1"].setChecked(False)
        assert not win.curves["ch1"].isVisible()

    def test_recheck_shows_curve(self, win, qtbot):
        win.checkboxes["ch1"].setChecked(False)
        win.checkboxes["ch1"].setChecked(True)
        assert win.curves["ch1"].isVisible()

    def test_other_curves_unaffected(self, win, qtbot):
        """Masquer ch1 ne touche pas ch2 et ch3."""
        win.checkboxes["ch1"].setChecked(False)
        assert win.curves["ch2"].isVisible()
        assert win.curves["ch3"].isVisible()

    def test_on_btn_pause_clicked_sets_event(self, win):
        assert not win.pause_event.is_set()
        win.on_btn_pause_clicked()
        assert win.pause_event.is_set()

    def test_on_btn_pause_clicked_clears_event(self, win):
        win.on_btn_pause_clicked()
        win.on_btn_pause_clicked()
        assert not win.pause_event.is_set()

    def test_on_btn_stop_clicked_sets_stop_event(self, win):
        """on_btn_stop_clicked() lève stop_event (même sans processus actif)."""
        import multiprocessing as mp
        win.process = mp.Process(target=lambda: None)  # dummy — non démarré
        win.on_btn_stop_clicked()
        assert win.stop_event.is_set()
