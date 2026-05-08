"""Tests du worker d'acquisition audio (processus séparé + mémoire partagée).

Tous les tests injectent FakeInputStream via la fixture fake_stream_factory pour
éviter tout accès matériel. Le patch est appliqué dans le processus parent
avant le fork, donc le processus enfant hérite de la version patchée.
"""
import time
import multiprocessing as mp
import numpy as np
import pytest

from test_multi_process_pandas.main import (
    acq_worker, BUFFER_SIZE, N_CHANNELS, CHUNK_SIZE, SAMPLE_RATE, SLEEP_LOOP,
)


def _start_worker(shm_pair, stream_factory=None):
    """Démarre acq_worker et retourne (process, pause_event, stop_event).

    Args:
        stream_factory: factory injectée dans acq_worker (FakeInputStream pour les tests).
    """
    shm_data, shm_meta, _, _ = shm_pair
    pause_event = mp.Event()
    stop_event  = mp.Event()
    p = mp.Process(
        target=acq_worker,
        args=(shm_data.name, shm_meta.name, pause_event, stop_event,
              stream_factory),
    )
    p.start()
    return p, pause_event, stop_event


def _wait_for_samples(meta, n, timeout=3.0):
    deadline = time.time() + timeout
    while int(meta[0]) < n and time.time() < deadline:
        time.sleep(0.01)


class TestAcqWorkerBasic:

    def test_writes_at_least_one_chunk(self, shm_pair, fake_stream_factory):
        """Le worker écrit au moins un bloc (CHUNK_SIZE frames) en moins de 3 s."""
        _, _, _, meta = shm_pair
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)
        stop.set(); p.join(timeout=2)

        assert int(meta[0]) >= CHUNK_SIZE

    def test_timestamp_is_recent(self, shm_pair, fake_stream_factory):
        """Les timestamps sont ancrés au démarrage du stream (t0 ≈ t_before).

        Seule la borne inférieure est vérifiable avec FakeInputStream : comme la
        stream ne bloque pas, frame_count peut traverser de nombreuses révolutions
        avant que stop_event soit traité, rendant toute borne supérieure invalide.
        """
        _, _, data, meta = shm_pair
        t_before = time.time()
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE * 2)
        stop.set(); p.join(timeout=2)

        margin = CHUNK_SIZE / SAMPLE_RATE      # ≈ 21 ms
        n = min(int(meta[0]), BUFFER_SIZE)
        assert np.all(data[:n, 0] >= t_before - margin), \
            "Des timestamps sont antérieurs au démarrage du stream"

    def test_timestamps_are_continuous(self, shm_pair, fake_stream_factory):
        """Les timestamps sont espacés exactement de 1/SAMPLE_RATE sans discontinuité.

        Avec le calcul par compteur (t0 + frame_count/SAMPLE_RATE), chaque pas
        entre deux frames consécutives (dans l'ordre physique du buffer) vaut
        1/SAMPLE_RATE, sauf au point de wrap-around du buffer circulaire où un
        saut négatif est attendu (au plus un seul).
        """
        _, _, data, meta = shm_pair
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, BUFFER_SIZE + CHUNK_SIZE)   # au moins un wrap
        stop.set(); p.join(timeout=2)

        n = min(int(meta[0]), BUFFER_SIZE)
        diffs = np.diff(data[:n, 0])
        expected_step = 1.0 / SAMPLE_RATE

        positive_diffs = diffs[diffs > 0]
        np.testing.assert_allclose(
            positive_diffs, expected_step, atol=1e-6,
            err_msg="Espacement entre timestamps invalide (gap inter-chunk détecté)"
        )
        assert np.sum(diffs < 0) <= 1, \
            "Plus d'un saut négatif détecté dans le buffer (wrap-around inattendu)"

    def test_channel_values_normalized(self, shm_pair, fake_stream_factory):
        """Les valeurs audio (sin/cos synthétiques) restent dans [−1, 1]."""
        _, _, data, meta = shm_pair
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)
        stop.set(); p.join(timeout=2)

        n = min(int(meta[0]), BUFFER_SIZE)
        assert np.all(np.abs(data[:n, 1:3]) <= 1.0 + 1e-9)

    def test_ch3_is_difference(self, shm_pair, fake_stream_factory):
        """ch3 = ch2 − ch1 pour chaque frame."""
        _, _, data, meta = shm_pair
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)
        stop.set(); p.join(timeout=2)

        n = min(int(meta[0]), BUFFER_SIZE)
        diff_expected = data[:n, 2] - data[:n, 1]
        np.testing.assert_allclose(data[:n, 3], diff_expected, atol=1e-12)

    def test_increments_meta_counter(self, shm_pair, fake_stream_factory):
        """meta[0] croît par multiples de CHUNK_SIZE."""
        _, _, _, meta = shm_pair
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)
        idx1 = int(meta[0])
        _wait_for_samples(meta, idx1 + CHUNK_SIZE)
        idx2 = int(meta[0])
        stop.set(); p.join(timeout=2)

        assert idx2 > idx1
        assert idx2 % CHUNK_SIZE == 0


class TestAcqWorkerControl:

    def test_stop_terminates_process(self, shm_pair, fake_stream_factory):
        """Le processus se termine proprement après stop_event."""
        _, _, _, meta = shm_pair
        p, _, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)
        stop.set()
        p.join(timeout=2)

        assert not p.is_alive()

    def test_pause_freezes_counter(self, shm_pair, fake_stream_factory):
        """meta[0] ne progresse plus pendant la pause."""
        _, _, _, meta = shm_pair
        p, pause, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)

        pause.set()
        time.sleep(SLEEP_LOOP * 4)
        idx_paused = int(meta[0])
        time.sleep(SLEEP_LOOP * 5)
        idx_after  = int(meta[0])

        stop.set(); p.join(timeout=2)

        # Au pire un bloc de plus (course entre pause et lecture audio)
        assert idx_after <= idx_paused + CHUNK_SIZE

    def test_resume_after_pause(self, shm_pair, fake_stream_factory):
        """Après reprise, le compteur recommence à progresser."""
        _, _, _, meta = shm_pair
        p, pause, stop = _start_worker(shm_pair, fake_stream_factory)
        _wait_for_samples(meta, CHUNK_SIZE)

        pause.set()
        time.sleep(SLEEP_LOOP * 3)
        idx_at_pause = int(meta[0])
        pause.clear()
        _wait_for_samples(meta, idx_at_pause + CHUNK_SIZE, timeout=3.0)

        stop.set(); p.join(timeout=2)

        assert int(meta[0]) > idx_at_pause
