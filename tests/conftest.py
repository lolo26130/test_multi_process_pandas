import os
import numpy as np
import pytest
from multiprocessing import shared_memory

# Qt headless pour les tests sans display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeInputStream:
    """Remplaçant de sounddevice.InputStream pour les tests.

    Génère un signal stéréo synthétique (sinus 440 Hz gauche, cosinus droit)
    sans aucun accès matériel audio.
    """

    def __init__(self, samplerate=44100, channels=2, dtype="float32",
                 blocksize=1024, **kwargs):
        self._samplerate = samplerate
        self._blocksize  = blocksize
        self._t          = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, n):
        t = self._t + np.arange(n) / self._samplerate
        self._t += n / self._samplerate
        left  = np.sin(2 * np.pi * 440 * t)
        right = np.cos(2 * np.pi * 440 * t)
        return np.column_stack([left, right]).astype("float32"), False


@pytest.fixture()
def fake_stream_factory():
    """Retourne FakeInputStream comme factory à injecter dans acq_worker.

    Utilisation : _start_worker(shm_pair, stream_factory=fake_stream_factory)
    Aucun accès matériel, aucun patch du module sounddevice.
    """
    return FakeInputStream

from test_multi_process_pandas.main import BUFFER_SIZE, N_CHANNELS, COLS, MainWindow


@pytest.fixture()
def shm_pair():
    """Paire de segments SharedMemory (data + meta) avec teardown automatique."""
    shm_data = shared_memory.SharedMemory(
        create=True, size=BUFFER_SIZE * (N_CHANNELS + 1) * 8
    )
    shm_meta = shared_memory.SharedMemory(create=True, size=2 * 8)

    data = np.ndarray((BUFFER_SIZE, N_CHANNELS + 1), dtype=np.float64, buffer=shm_data.buf)
    meta = np.ndarray((2,), dtype=np.int64, buffer=shm_meta.buf)
    data[:] = 0
    meta[:] = 0

    yield shm_data, shm_meta, data, meta

    shm_data.close(); shm_data.unlink()
    shm_meta.close(); shm_meta.unlink()


@pytest.fixture()
def win(qtbot):
    """MainWindow avec cleanup via closeEvent (arrête le watcher + libère la mémoire).

    qtbot.addWidget appelle window.close() au teardown, ce qui déclenche
    closeEvent → pas besoin de close() explicite ici.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    return window
