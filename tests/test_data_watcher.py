"""Tests du pont DataWatcher : mp.Queue → signal Qt data_ready."""
import multiprocessing as mp
import pytest
from PyQt6.QtCore import QThread

from test_multi_process_pandas.main import DataWatcher


@pytest.fixture()
def watcher_in_thread(qtbot):
    """DataWatcher démarré dans son propre QThread ; teardown propre garanti."""
    queue   = mp.Queue()
    watcher = DataWatcher(queue)
    thread  = QThread()
    watcher.moveToThread(thread)
    thread.started.connect(watcher.run)
    thread.start()

    yield watcher, thread, queue

    watcher.stop()
    thread.quit()
    thread.wait(500)


class TestDataWatcherSignal:

    def test_emits_data_ready_on_item(self, qtbot, watcher_in_thread):
        """data_ready est émis dès qu'un item arrive dans la queue."""
        watcher, _, queue = watcher_in_thread
        # queue.put() DANS le with : la connexion waitSignal est établie avant le trigger
        with qtbot.waitSignal(watcher.data_ready, timeout=1000) as blocker:
            queue.put(42)
        assert blocker.args == [42]

    def test_transmits_exact_idx(self, qtbot, watcher_in_thread):
        """La valeur émise correspond exactement à l'idx mis dans la queue."""
        watcher, _, queue = watcher_in_thread
        for idx in [1, 99, 1000]:
            with qtbot.waitSignal(watcher.data_ready, timeout=1000) as blocker:
                queue.put(idx)
            assert blocker.args == [idx]

    def test_emits_once_per_item(self, qtbot, watcher_in_thread):
        """Chaque item produit exactement un signal, pas plus."""
        watcher, _, queue = watcher_in_thread
        received = []
        watcher.data_ready.connect(received.append)

        for i in range(5):
            queue.put(i)

        qtbot.waitUntil(lambda: len(received) == 5, timeout=2000)
        assert received == list(range(5))


class TestDataWatcherLifecycle:

    def test_stop_terminates_thread(self, qtbot, watcher_in_thread):
        """stop() + quit() font terminer le thread en moins de 500 ms."""
        watcher, thread, _ = watcher_in_thread
        watcher.stop()
        thread.quit()
        assert thread.wait(500), "Le thread DataWatcher n'a pas terminé dans les temps"

    def test_no_emission_after_stop(self, qtbot, watcher_in_thread):
        """Aucun signal n'est émis après stop()."""
        watcher, thread, queue = watcher_in_thread
        received = []
        watcher.data_ready.connect(received.append)

        watcher.stop()
        thread.quit()
        thread.wait(500)

        queue.put(99)
        qtbot.wait(200)   # laisse le temps d'émettre si le bug existe

        assert received == []
