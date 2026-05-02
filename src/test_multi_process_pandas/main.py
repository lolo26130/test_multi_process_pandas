import sys
import time
import multiprocessing as mp
import numpy as np
import pandas as pd

from pathlib import Path
from multiprocessing import shared_memory
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QThread, QObject, pyqtSignal
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

BUFFER_SIZE = 1000
CHANNEL_NAMES = ["ch1", "ch2", "ch3"]
COLS = ["t"] + CHANNEL_NAMES
N_CHANNELS = len(CHANNEL_NAMES)

WINDOW_SEC = 5.0  # last N seconds for
SLEEP_LOOP = 0.05


pg.setConfigOptions(useOpenGL=True)  # TODO acceleration OpenGL (to test)

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

def acq_worker(data_name, meta_name, queue, pause_event, stop_event):
    shm_data = shared_memory.SharedMemory(name=data_name)
    shm_meta = shared_memory.SharedMemory(name=meta_name)

    data = np.ndarray((BUFFER_SIZE, N_CHANNELS + 1), dtype=np.float64, buffer=shm_data.buf)
    meta = np.ndarray((2,), dtype=np.int64, buffer=shm_meta.buf)

    idx = 0
    k = 10

    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue

        t = time.time()

        values = np.array([
            np.sin(idx * 0.1) + np.random.randn(1)[0] / k,
            np.cos(idx * 0.1) + np.random.randn(1)[0] / k,
            np.sin(idx * 0.05) + np.random.randn(1)[0] / k,
        ])

        pos = idx % BUFFER_SIZE
        data[pos, 0] = t
        data[pos, 1:] = values

        idx += 1
        meta[0] = idx

        if queue.qsize() < 10:
            queue.put(idx)
        time.sleep(SLEEP_LOOP)

    shm_data.close()
    shm_meta.close()

class DataWatcher(QObject):
    data_ready = pyqtSignal(int)

    def __init__(self, mp_queue):
        super().__init__()
        self._queue = mp_queue
        self._running = True

    def run(self):
        while self._running:
            try:
                idx = self._queue.get(timeout=0.1)
                self.data_ready.emit(idx)
            except mp.queues.Empty:
                pass

    def stop(self):
        self._running = False


class MainWindow(QWidget, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # DateAxisItem ne peut pas être défini dans Qt Designer
        self.plot.getPlotItem().setAxisItems({'bottom': pg.DateAxisItem()})

        # curves dict
        self.curves = {name: self.plot.plot(name=name) for name in CHANNEL_NAMES}

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

        # signals
        self.btn_start.clicked.connect(self.start_acq)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop_acq)
        self.btn_kill.clicked.connect(self.kill_acq)

        # watcher thread : surveille la queue du process et émet data_ready
        self.watcher = DataWatcher(self.queue)
        self.watcher_thread = QThread()
        self.watcher.moveToThread(self.watcher_thread)
        self.watcher_thread.started.connect(self.watcher.run)
        self.watcher.data_ready.connect(self.on_data_ready)
        self.watcher_thread.start()

    def log_msg(self, msg):
        self.log.append(str(msg))

    def start_acq(self):
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

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pause_event.set()
        else:
            self.pause_event.clear()

    def stop_acq(self):
        if self.process:
            self.stop_event.set()

    def kill_acq(self):
        if self.process:
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
        for name, cb in self.checkboxes.items():
            self.curves[name].setVisible(cb.isChecked())

    def get_views(self):
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
        self.log_msg(idx)
        self.update_ui_rolling()

    def update_ui_rolling(self):
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
        self.watcher.stop()
        self.watcher_thread.quit()
        self.watcher_thread.wait()

        if self.process:
            self.process.terminate()
            self.process.join()

        self.shm_data.close()
        self.shm_data.unlink()

        self.shm_meta.close()
        self.shm_meta.unlink()

        event.accept()


def main():
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


