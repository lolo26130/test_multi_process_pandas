import os
import numpy as np
import pytest
from multiprocessing import shared_memory

# Qt headless pour les tests sans display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
