"""Tests de la compilation automatique views/main.ui → views/ui_main.py."""
import os
import time
import pytest

from test_multi_process_pandas.main import _compile_ui, _UI_SRC


def test_creates_file(tmp_path, monkeypatch):
    """ui_main.py est créé s'il n'existe pas encore."""
    py_path = tmp_path / "ui_main.py"
    monkeypatch.setattr("test_multi_process_pandas.main._UI_PY", py_path)

    _compile_ui()

    assert py_path.exists()
    assert "Ui_MainWindow" in py_path.read_text()


def test_skips_if_up_to_date(tmp_path, monkeypatch):
    """Pas de recompilation si ui_main.py est plus récent que main.ui."""
    py_path = tmp_path / "ui_main.py"
    monkeypatch.setattr("test_multi_process_pandas.main._UI_PY", py_path)

    _compile_ui()
    mtime_after_first = py_path.stat().st_mtime
    time.sleep(0.05)
    _compile_ui()

    assert py_path.stat().st_mtime == mtime_after_first


def test_recompiles_if_ui_newer(tmp_path, monkeypatch):
    """Recompilation forcée si main.ui est plus récent que ui_main.py."""
    py_path = tmp_path / "ui_main.py"
    monkeypatch.setattr("test_multi_process_pandas.main._UI_PY", py_path)

    _compile_ui()
    # Antidater ui_main.py pour simuler un .ui modifié après
    stale_mtime = _UI_SRC.stat().st_mtime - 10
    os.utime(py_path, (stale_mtime, stale_mtime))

    _compile_ui()

    assert py_path.stat().st_mtime > stale_mtime


def test_generated_content_is_valid_python(tmp_path, monkeypatch):
    """Le fichier généré est du Python valide contenant la classe Ui_MainWindow."""
    py_path = tmp_path / "ui_main.py"
    monkeypatch.setattr("test_multi_process_pandas.main._UI_PY", py_path)

    _compile_ui()
    source = py_path.read_text()

    compile(source, str(py_path), "exec")   # lève SyntaxError si invalide
    assert "class Ui_MainWindow" in source
    assert "def setupUi" in source
