"""Tests du worker d'acquisition (processus séparé + mémoire partagée)."""
import time
import multiprocessing as mp
import numpy as np
import pytest

from test_multi_process_pandas.main import acq_worker, BUFFER_SIZE, N_CHANNELS, SLEEP_LOOP


def _start_worker(shm_pair):
    """Démarre acq_worker et retourne (process, queue, pause_event, stop_event)."""
    shm_data, shm_meta, _, _ = shm_pair
    queue       = mp.Queue()
    pause_event = mp.Event()
    stop_event  = mp.Event()
    p = mp.Process(
        target=acq_worker,
        args=(shm_data.name, shm_meta.name, queue, pause_event, stop_event),
    )
    p.start()
    return p, queue, pause_event, stop_event


def _wait_for_samples(meta, n, timeout=3.0):
    deadline = time.time() + timeout
    while int(meta[0]) < n and time.time() < deadline:
        time.sleep(0.01)


class TestAcqWorkerBasic:

    def test_writes_at_least_one_sample(self, shm_pair):
        """Le worker écrit au moins un échantillon en moins de 3 secondes."""
        _, _, _, meta = shm_pair
        p, _, _, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 1)
        stop.set(); p.join(timeout=2)

        assert int(meta[0]) >= 1

    def test_timestamp_is_recent(self, shm_pair):
        """La colonne t contient des timestamps Unix contemporains."""
        _, _, data, meta = shm_pair
        t_before = time.time()
        p, _, _, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 3)
        t_after = time.time()
        stop.set(); p.join(timeout=2)

        n = min(int(meta[0]), BUFFER_SIZE)
        for i in range(n):
            assert t_before <= data[i, 0] <= t_after, (
                f"timestamp data[{i},0]={data[i,0]:.3f} hors de [{t_before:.3f}, {t_after:.3f}]"
            )

    def test_channel_values_are_bounded(self, shm_pair):
        """Les valeurs sin/cos + bruit restent dans [-2, 2]."""
        _, _, data, meta = shm_pair
        p, _, _, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 5)
        stop.set(); p.join(timeout=2)

        n = min(int(meta[0]), BUFFER_SIZE)
        assert np.all(np.abs(data[:n, 1:]) <= 2.0)

    def test_increments_meta_counter(self, shm_pair):
        """meta[0] croît strictement au fil des échantillons."""
        _, _, _, meta = shm_pair
        p, _, _, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 1)
        idx1 = int(meta[0])
        _wait_for_samples(meta, idx1 + 3)
        idx2 = int(meta[0])
        stop.set(); p.join(timeout=2)

        assert idx2 > idx1


class TestAcqWorkerControl:

    def test_stop_terminates_process(self, shm_pair):
        """Le processus se termine proprement après stop_event."""
        _, _, _, meta = shm_pair
        p, _, _, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 1)
        stop.set()
        p.join(timeout=2)

        assert not p.is_alive()

    def test_pause_freezes_counter(self, shm_pair):
        """meta[0] ne progresse plus pendant la pause."""
        _, _, _, meta = shm_pair
        p, _, pause, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 2)

        pause.set()
        time.sleep(SLEEP_LOOP * 3)     # ≥ 3 cycles de sleep du worker
        idx_paused = int(meta[0])
        time.sleep(SLEEP_LOOP * 5)
        idx_after  = int(meta[0])

        stop.set(); p.join(timeout=2)

        # Au pire 1 échantillon de plus (course entre pause et écriture)
        assert idx_after <= idx_paused + 1

    def test_resume_after_pause(self, shm_pair):
        """Après reprise, le compteur recommence à progresser."""
        _, _, _, meta = shm_pair
        p, _, pause, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 2)

        pause.set()
        time.sleep(SLEEP_LOOP * 3)
        idx_at_pause = int(meta[0])
        pause.clear()
        _wait_for_samples(meta, idx_at_pause + 3, timeout=3.0)

        stop.set(); p.join(timeout=2)

        assert int(meta[0]) > idx_at_pause

    def test_queue_receives_notifications(self, shm_pair):
        """La queue reçoit des idx à chaque lot d'échantillons."""
        _, _, _, meta = shm_pair
        p, queue, _, stop = _start_worker(shm_pair)
        _wait_for_samples(meta, 5)
        stop.set(); p.join(timeout=2)

        assert not queue.empty()
        idx = queue.get_nowait()
        assert isinstance(idx, int) and idx >= 1
