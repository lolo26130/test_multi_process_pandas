import os
import shutil
import subprocess
import sys
import time
import multiprocessing as mp
import numpy as np
import pandas as pd

from pathlib import Path
from multiprocessing import shared_memory
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot
from PyQt6 import uic

import pyqtgraph as pg

# enregistre les ressources Qt (:/record/... :/icons/...) avant tout setupUi()
from test_multi_process_pandas.resources.icons import Boutons_rc  # noqa: F401

_UI_SRC = Path(__file__).parent / "views" / "main.ui"
_UI_PY  = Path(__file__).parent / "views" / "ui_main.py"


def _compile_ui():
    """Recompile views/main.ui → views/ui_main.py si le .ui est plus récent."""
    if not _UI_PY.exists() or _UI_SRC.stat().st_mtime > _UI_PY.stat().st_mtime:
        with open(_UI_PY, "w", encoding="utf-8") as fout:
            uic.compileUi(str(_UI_SRC), fout)

_compile_ui()
from test_multi_process_pandas.views.ui_main import Ui_MainWindow  # noqa: E402

#: Fréquence d'échantillonnage audio en Hz.
#: 48000 = taux natif du codec ALSA (hw:1,0 SN6140). Ne pas utiliser 44100 sur
#: ce périphérique — le driver ALSA direct ne fait pas de conversion de fréquence.
SAMPLE_RATE = 48000

#: Nombre de frames audio lues par bloc (latence ≈ CHUNK_SIZE / SAMPLE_RATE s).
CHUNK_SIZE = 1024

#: Taille du buffer circulaire en frames — correspond à SAMPLE_RATE * 2 secondes d'audio.
BUFFER_SIZE = SAMPLE_RATE * 2

#: Noms des canaux — ch1 gauche, ch2 droite, ch3 différence ch2 moins ch1.
#: Chaque entrée correspond à une colonne de données et à une checkbox dans l'interface.
CHANNEL_NAMES = ["ch1", "ch2", "ch3"]

COLS = ["t"] + CHANNEL_NAMES
N_CHANNELS = len(CHANNEL_NAMES)

#: Durée de sommeil (s) pendant la pause — laisse le CPU libre entre deux vérifications.
SLEEP_LOOP = 0.05

#: Période minimale (s) entre deux rafraîchissements du graphe (≈ 30 Hz).
PLOT_PERIOD = 1.0 / 30.0

#: Période minimale (s) entre deux entrées dans le log (≈ 2 Hz).
LOG_PERIOD = 0.5

#: Nombre maximum de lignes conservées dans le log.
LOG_MAX_LINES = 200


pg.setConfigOptions(useOpenGL=False)  # OpenGL désactivé : QOpenGLWidget non supporté sur ce système

# Ordre de préférence des émulateurs de terminal disponibles sur le système.
# Chaque entrée est la liste d'arguments précédant la commande à exécuter.
_TERMINAL_CANDIDATES = [
    ["konsole", "-e"],
    ["xterm", "-e"],
    ["gnome-terminal", "--"],
    ["alacritty", "-e"],
    ["kitty"],
]


def _find_terminal() -> "list[str] | None":
    """Retourne les arguments de lancement du premier terminal trouvé dans PATH."""
    for args in _TERMINAL_CANDIDATES:
        if shutil.which(args[0]):
            return args
    return None

# def downsample_minmax(x, y, max_points):
#     n = len(x)
#     if n <= max_points:
#         return x, y

#     bucket_size = n // max_points

#     x_out = []
#     y_out = []

#     for i in range(0, n, bucket_size):
#         xs = x[i:i + bucket_size]
#         ys = y[i:i + bucket_size]

#         if len(xs) == 0:
#             continue

#         ymin = ys.min()
#         ymax = ys.max()

#         xmin = xs[ys.argmin()]
#         xmax = xs[ys.argmax()]

#         x_out.extend([xmin, xmax])
#         y_out.extend([ymin, ymax])

#     return np.array(x_out), np.array(y_out)

def acq_worker(data_name, meta_name, queue, pause_event, stop_event,
               _stream_factory=None):
    """Worker d'acquisition audio exécuté dans un processus séparé (multiprocessing).

    Ouvre le périphérique d'entrée par défaut via sounddevice en mode stéréo et
    lit des blocs de CHUNK_SIZE frames à SAMPLE_RATE Hz. Chaque bloc est écrit
    en une seule opération numpy dans le buffer circulaire en mémoire partagée.

    sounddevice est importé à l'intérieur de la fonction pour éviter que PortAudio
    soit initialisé dans le processus parent avant le fork (ce qui corromprait
    l'état du backend audio dans le processus enfant).

    Canaux écrits :
        - col 0 : timestamp Unix de chaque frame (interpolé sur le bloc).
        - col 1 (ch1) : canal gauche (float64, normalisé −1 … +1).
        - col 2 (ch2) : canal droit  (float64, normalisé −1 … +1).
        - col 3 (ch3) : différence ch2 − ch1.

    La progression est signalée au processus principal via *queue* (idx courant).
    L'envoi dans la queue est limité (qsize < 10) pour éviter l'accumulation.

    Args:
        data_name:        nom du segment SharedMemory portant le buffer de données
                          (BUFFER_SIZE × (N_CHANNELS+1) float64).
        meta_name:        nom du segment SharedMemory portant le compteur d'index
                          (tableau int64[2], seul meta[0] est utilisé).
        queue:            mp.Queue de notification vers le thread DataWatcher.
        pause_event:      mp.Event levé pour suspendre l'acquisition sans fermer le stream.
        stop_event:       mp.Event levé pour terminer la boucle proprement.
        _stream_factory:  callable() → context manager compatible sounddevice.InputStream.
                          Si None, utilise sounddevice avec les constantes du module.
                          Réservé aux tests (injection de FakeInputStream).
    """
    import sounddevice as sd  # import après le fork — PortAudio initialisé dans l'enfant

    if _stream_factory is None:
        def _stream_factory():
            return sd.InputStream(samplerate=SAMPLE_RATE, channels=2,
                                  dtype="float32", blocksize=CHUNK_SIZE)

    shm_data = shared_memory.SharedMemory(name=data_name)
    shm_meta = shared_memory.SharedMemory(name=meta_name)

    data = np.ndarray((BUFFER_SIZE, N_CHANNELS + 1), dtype=np.float64, buffer=shm_data.buf)
    meta = np.ndarray((2,), dtype=np.int64, buffer=shm_meta.buf)

    idx = 0

    with _stream_factory() as stream:
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(SLEEP_LOOP)
                continue

            audio, _ = stream.read(CHUNK_SIZE)   # shape : (CHUNK_SIZE, 2), float32
            n = len(audio)

            # Timestamps interpolés sur le bloc
            t_end    = time.time()
            t_start  = t_end - n / SAMPLE_RATE
            timestamps = t_start + np.arange(n) / SAMPLE_RATE

            # Cast float32 → float64 (format du buffer shared memory)
            left  = audio[:, 0].astype(np.float64)
            right = audio[:, 1].astype(np.float64)
            diff  = right - left

            # Écriture en bulk dans le buffer circulaire (gestion du wrap-around)
            start = idx % BUFFER_SIZE
            if start + n <= BUFFER_SIZE:
                data[start:start + n, 0] = timestamps
                data[start:start + n, 1] = left
                data[start:start + n, 2] = right
                data[start:start + n, 3] = diff
            else:
                first = BUFFER_SIZE - start
                data[start:,        0] = timestamps[:first]
                data[start:,        1] = left[:first]
                data[start:,        2] = right[:first]
                data[start:,        3] = diff[:first]
                data[:n - first,    0] = timestamps[first:]
                data[:n - first,    1] = left[first:]
                data[:n - first,    2] = right[first:]
                data[:n - first,    3] = diff[first:]

            idx += n
            meta[0] = idx

            if queue.qsize() < 10:
                queue.put(idx)

    shm_data.close()
    shm_meta.close()

class DataWatcher(QObject):
    """Pont entre la mp.Queue du processus d'acquisition et le système de signaux Qt.

    Vit dans un QThread dédié. Bloque sur mp.Queue.get() avec un timeout de
    100 ms, ce qui permet à la boucle de se terminer proprement sans polling
    actif. Chaque idx reçu est retransmis au thread GUI via le signal data_ready,
    qui est automatiquement mis en file (queued connection) par Qt.

    Signal:
        data_ready(int): émis avec l'index d'échantillon courant dès qu'un
                         nouveau lot de données est disponible en mémoire partagée.
    """

    #: Émis avec l'index courant (``meta[0]``) dès qu'un nouvel échantillon
    #: est disponible en mémoire partagée. Connecté à
    #: :meth:`~test_multi_process_pandas.main.MainWindow.on_data_ready`
    #: via une queued connection Qt (thread-safe).
    data_ready = pyqtSignal(int)

    def __init__(self, mp_queue):
        """Args:
            mp_queue: la mp.Queue produite par acq_worker à surveiller.
        """
        super().__init__()
        self._queue = mp_queue
        self._running = True

    def run(self):
        """Boucle de surveillance, à connecter à QThread.started.

        Bloque sur la queue avec un timeout de 100 ms pour rester réactif
        à l'appel de stop() sans consommer de CPU inutilement.
        """
        while self._running:
            try:
                idx = self._queue.get(timeout=0.1)
                self.data_ready.emit(idx)
            except mp.queues.Empty:
                pass

    def stop(self):
        """Demande l'arrêt propre de la boucle run() au prochain timeout."""
        self._running = False


class MainWindow(QWidget, Ui_MainWindow):
    """Fenêtre principale de l'application.

    Hérite de QWidget (widget racine) et de Ui_MainWindow (layout compilé depuis
    views/main.ui). Orchestre trois composants indépendants :

    - Le processus d'acquisition (acq_worker) qui écrit dans la mémoire partagée.
    - Le thread DataWatcher qui surveille la mp.Queue et émet data_ready.
    - L'affichage pyqtgraph mis à jour sur réception du signal data_ready.

    La mémoire partagée est organisée en buffer circulaire de BUFFER_SIZE lignes ×
    (1 timestamp + N_CHANNELS valeurs). Un DataFrame pandas en vue zero-copy
    (df_view) permet de lire ce buffer sans allocation supplémentaire.
    """

    def __init__(self):
        """Initialise la fenêtre : UI, mémoire partagée, processus et thread watcher."""
        super().__init__()
        self.setupUi(self)

        # DateAxisItem ne peut pas être défini dans Qt Designer
        self.plot.getPlotItem().setAxisItems({'bottom': pg.DateAxisItem()})

        # curves dict — downsampling auto : pyqtgraph réduit les points au nombre
        # de pixels disponibles, ce qui est essentiel avec 96 000 pts/courbe
        self.curves = {}
        for name in CHANNEL_NAMES:
            curve = self.plot.plot(name=name)
            curve.setDownsampling(auto=True, method='peak')
            curve.setClipToView(True)
            self.curves[name] = curve

        # checkboxes dict mappé depuis les widgets du .ui (cb_ch1, cb_ch2, cb_ch3)
        self.checkboxes = {name: getattr(self, f"cb_{name}") for name in CHANNEL_NAMES}
        for cb in self.checkboxes.values():
            cb.stateChanged.connect(self.update_visibility)

        # shared memory
        self.shm_data = shared_memory.SharedMemory(
            create=True,
            size=BUFFER_SIZE * (N_CHANNELS + 1) * 8
        )
        self.data = np.ndarray(
            (BUFFER_SIZE, N_CHANNELS + 1),
            dtype=np.float64,
            buffer=self.shm_data.buf
        )
        self.data[:] = 0
        self.df_view = pd.DataFrame(self.data, columns=COLS)  # dataframe zero-copy

        self.shm_meta = shared_memory.SharedMemory(create=True, size=2 * 8)
        self.meta = np.ndarray((2,), dtype=np.int64, buffer=self.shm_meta.buf)
        self.meta[:] = 0

        # multiprocessing
        self.queue = mp.Queue()
        self.pause_event = mp.Event()
        self.stop_event = mp.Event()
        self.process = None
        self.paused = False
        self.monitor_proc = None  # processus terminal hébergeant process_monitor

        # cap du log + horodatages de throttling
        self.log.document().setMaximumBlockCount(LOG_MAX_LINES)
        self._t_last_log  = 0.0
        self._t_last_plot = 0.0

        # watcher thread : surveille la queue du process et émet data_ready
        self.watcher = DataWatcher(self.queue)
        self.watcher_thread = QThread()
        self.watcher.moveToThread(self.watcher_thread)
        self.watcher_thread.started.connect(self.watcher.run)
        self.watcher.data_ready.connect(self.on_data_ready)
        self.watcher_thread.start()

    def _launch_monitor(self) -> None:
        """Ouvre un terminal avec process_monitor pour acq_worker et ce processus."""
        if self.process is None or not self.process.is_alive():
            return
        term = _find_terminal()
        if term is None:
            self.log_msg("[monitor] Aucun terminal disponible (konsole, xterm…).")
            return
        cmd = term + [
            sys.executable, "-m", "test_multi_process_pandas.process_monitor",
            "--child-pid",  str(self.process.pid),
            "--parent-pid", str(os.getpid()),
        ]
        self.monitor_proc = subprocess.Popen(cmd)

    def _stop_monitor(self) -> None:
        """Termine le terminal de monitoring s'il tourne encore."""
        if self.monitor_proc and self.monitor_proc.poll() is None:
            self.monitor_proc.terminate()
        self.monitor_proc = None

    def log_msg(self, msg):
        """Ajoute une ligne dans le QTextEdit de log."""
        self.log.append(str(msg))

    @pyqtSlot()
    def on_btn_start_clicked(self):
        """Démarre le processus d'acquisition s'il n'est pas déjà actif.

        Réinitialise les événements stop et pause avant de lancer acq_worker
        dans un nouveau mp.Process. Sans effet si un processus tourne déjà.
        """
        if self.process and self.process.is_alive():
            return

        self.stop_event.clear()
        self.pause_event.clear()

        self.process = mp.Process(
            target=acq_worker,
            args=(
                self.shm_data.name,
                self.shm_meta.name,
                self.queue,
                self.pause_event,
                self.stop_event,
            ),
        )
        self.process.start()
        self._launch_monitor()

    @pyqtSlot()
    def on_btn_pause_clicked(self):
        """Bascule l'état pause/reprise de l'acquisition.

        Lève ou efface pause_event, que acq_worker lit à chaque itération.
        """
        self.paused = not self.paused
        if self.paused:
            self.pause_event.set()
        else:
            self.pause_event.clear()

    @pyqtSlot()
    def on_btn_stop_clicked(self):
        """Arrêt gracieux : lève stop_event pour que acq_worker termine sa boucle."""
        if self.process:
            self.stop_event.set()

    @pyqtSlot()
    def on_btn_kill_clicked(self):
        """Arrêt forcé : envoie SIGTERM au processus et attend sa terminaison."""
        self._stop_monitor()
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join()

    # def get_ordered_df(self):
    #     idx = int(self.meta[0])
    #     if idx == 0:
    #         return None

    #     pos = idx % BUFFER_SIZE

    #     if idx < BUFFER_SIZE:
    #         arr = self.data[:idx]
    #     else:
    #         arr = np.vstack((self.data[pos:], self.data[:pos]))

    #     return pd.DataFrame(arr, columns=COLS)

    def update_visibility(self):
        """Affiche ou masque chaque courbe selon l'état de sa checkbox associée."""
        for name, cb in self.checkboxes.items():
            self.curves[name].setVisible(cb.isChecked())

    def get_views(self):
        """Retourne une ou deux vues pandas zero-copy sur le buffer circulaire,
        dans l'ordre chronologique des données.

        Le buffer est rempli en spirale (pos = idx % BUFFER_SIZE). Quand il
        n'est pas encore plein (idx < BUFFER_SIZE), une seule vue suffit.
        Une fois plein, deux vues contiguës sont nécessaires : la partie
        [pos:] (ancienne) suivie de [:pos] (récente).

        Returns:
            (v1, None)  si le buffer est partiellement rempli.
            (v1, v2)    si le buffer est plein (v1 ancienne, v2 récente).
            (None, None) si aucune donnée n'a encore été écrite.
        """
        idx = int(self.meta[0])
        if idx == 0:
            return None, None

        pos = idx % BUFFER_SIZE

        if idx < BUFFER_SIZE:
            return self.df_view.iloc[:idx], None

        #  deux vues, PAS UNE copie
        return (
            self.df_view.iloc[pos:],   # fin
            self.df_view.iloc[:pos],   # début
        )

    def on_data_ready(self, idx):
        """Slot connecté à DataWatcher.data_ready (thread GUI).

        Le worker audio émet ~43 notifications/seconde (44100 / 1024). Ce slot
        découple le taux d'acquisition du taux d'affichage via deux throttles
        indépendants basés sur ``time.monotonic()`` :

        - **Log** : limité à ``LOG_PERIOD`` s (~2 Hz) pour éviter que le
          QTextEdit accapare le thread GUI avec des repaints à haute fréquence.
        - **Plot** : limité à ``PLOT_PERIOD`` s (~30 Hz) pour un rendu fluide
          sans saturer pyqtgraph.

        Ignoré intégralement si ``_closed`` est levé (shared memory libérée).

        Args:
            idx: index courant du buffer (meta[0] dans la mémoire partagée).
        """
        if getattr(self, '_closed', False):
            return

        now = time.monotonic()

        if now - self._t_last_log >= LOG_PERIOD:
            self._t_last_log = now
            self.log_msg(idx)

        if now - self._t_last_plot >= PLOT_PERIOD:
            self._t_last_plot = now
            if self.rb_rolling.isChecked():
                self.update_ui_rolling()
            else:
                self.update_ui()

    def update_ui(self):
        """Affichage direct du buffer — mode économique, zéro copie, zéro allocation.

        Lit ``self.data[:n, col]`` comme vue numpy brute sans passer par pandas,
        sans concaténation et sans réordonnancement chronologique.
        L'axe X est l'indice d'échantillon (implicite dans pyqtgraph).

        Quand le buffer est plein (idx ≥ BUFFER_SIZE), les données sont affichées
        dans l'ordre physique du buffer : un saut visuel peut apparaître au point
        de wrap-around, ce qui est le compromis accepté pour économiser le CPU.
        """
        idx = int(self.meta[0])
        if idx == 0:
            return
        n = min(idx, BUFFER_SIZE)
        for i, name in enumerate(CHANNEL_NAMES):
            if not self.checkboxes[name].isChecked():
                continue
            self.curves[name].setData(self.data[:n, i + 1])

    def update_ui_rolling(self):
        """Met à jour les courbes pyqtgraph à partir de l'état courant du buffer.

        Lit les vues zero-copy via get_views() et concatène les segments numpy
        (np.concatenate) sans copie lourde pour reconstruire l'axe temporel
        continu. Seules les courbes dont la checkbox est cochée sont rafraîchies.
        """
        views = self.get_views()
        if views is None:
            return

        v1, v2 = views

        for name in CHANNEL_NAMES:
            if not self.checkboxes[name].isChecked():
                continue

            if v1 is not None and v2 is not None:
                # concat logique sans copie lourde
                t = np.concatenate((v1["t"].values, v2["t"].values))
                y = np.concatenate((v1[name].values, v2[name].values))
                self.curves[name].setData(t, y)
            if v2 is None and v1 is not None:
                t = v1["t"].values
                y = v1[name].values
                self.curves[name].setData(t, y)
            if v2 is not None and v1 is None:
                t = v1["t"].values
                y = v1[name].values
                self.curves[name].setData(t, y)
            if v2 is None and v1 is None:
                pass

    # def update_ui(self):
    #     while not self.queue.empty():
    #         self.log_msg(self.queue.get())

    #     df = self.get_ordered_df()
    #     if df is None:
    #         return

    #     t = df["t"] - df["t"].min()

    #     for name in CHANNEL_NAMES:
    #         if self.checkboxes[name].isChecked():
    #             self.curves[name].setData(t, df[name])

    # def update_ui_rolling(self):
    #     while not self.queue.empty():
    #         self.log_msg(self.queue.get())

    #     df = self.get_ordered_df()
    #     if df is None or df.empty:
    #         return

    #     t = df["t"]
    #     t0 = t.max()
    #     t_rel = t - t0

    #     # rolling window filter
    #     mask = t_rel >= -WINDOW_SEC
    #     dfw = df[mask]

    #     t_plot = dfw["t"] - dfw["t"].min()

    #     for name in CHANNEL_NAMES:
    #         if self.checkboxes[name].isChecked():
    #             self.curves[name].setData(t_plot, dfw[name])   # TODO ? plante 

    # def update_ui_downsampling(self):    # TODO to test ....
    #     while not self.queue.empty():
    #         self.log_msg(self.queue.get())

    #     df = self.get_ordered_df()
    #     if df is None or df.empty:
    #         return

    #     t = df["t"]
    #     t0 = t.max()
    #     t_rel = t - t0

    #     # rolling window
    #     mask = t_rel >= -WINDOW_SEC
    #     dfw = df[mask]

    #     if dfw.empty:
    #         return

    #     # downsampling
    #     n = len(dfw)
    #     if n > MAX_POINTS:
    #         step = max(1, n // MAX_POINTS)
    #         dfw = dfw.iloc[::step]

    #     t_plot = dfw["t"] - dfw["t"].min()

    #     for name in CHANNEL_NAMES:
    #         if self.checkboxes[name].isChecked():
    #             self.curves[name].setData(t_plot, dfw[name])




    #     # t_plot = (dfw["t"] - dfw["t"].min()).to_numpy()  # TODO test ????: min max enveloppe 

    #     # for name in CHANNEL_NAMES:
    #     #     if not self.checkboxes[name].isChecked():
    #     #         continue

    #     #     y = dfw[name].to_numpy()

    #     #     x_ds, y_ds = downsample_minmax(t_plot, y, MAX_POINTS)

    #     #     self.curves[name].setData(x_ds, y_ds)



    def closeEvent(self, event):
        """Nettoyage ordonné à la fermeture de la fenêtre.

        Ordre d'arrêt (chaque étape dépend de la précédente) :

        1. Lever ``_closed`` — court-circuite les slots qui accèdent à la
           shared memory (signaux Qt encore en file d'attente).
        2. Arrêter le thread DataWatcher — garantit qu'aucun nouveau signal
           ``data_ready`` ne sera émis.
        3. Terminer le processus acq_worker.
        4. Libérer et détruire les segments SharedMemory.

        La méthode est idempotente : un second appel (Qt peut la déclencher
        deux fois) est ignoré via le flag ``_closed``.
        """
        if getattr(self, '_closed', False):
            event.accept()
            return
        self._closed = True

        self._stop_monitor()

        self.watcher.stop()
        self.watcher_thread.quit()
        self.watcher_thread.wait()

        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join()

        self.shm_data.close()
        try:
            self.shm_data.unlink()
        except FileNotFoundError:
            pass

        self.shm_meta.close()
        try:
            self.shm_meta.unlink()
        except FileNotFoundError:
            pass

        event.accept()


def main():
    """Point d'entrée de l'application Qt.

    Crée la QApplication, instancie MainWindow et entre dans la boucle
    d'événements. Doit être appelé après freeze_support() et la sélection
    de la méthode de démarrage multiprocessing.
    """
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(900, 600)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # import multiprocessing as mp
    # import sys

    mp.freeze_support()

    if sys.platform.startswith("linux"):
        mp.set_start_method("fork", force=True)
    else:
        mp.set_start_method("spawn", force=True)

    main()

# def main():
#     mp.set_start_method("spawn")

#     app = QApplication(sys.argv)
#     win = MainWindow()
#     win.resize(900, 600)
#     win.show()
#     sys.exit(app.exec())
    
    
# if __name__ == "__main__":
#     mp.freeze_support()
#     main()


