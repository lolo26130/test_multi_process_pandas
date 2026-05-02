import sys
import time
import multiprocessing as mp
import numpy as np
import pandas as pd

from multiprocessing import shared_memory
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QTextEdit, QCheckBox, QHBoxLayout
)
from PyQt6.QtCore import QTimer

import pyqtgraph as pg

BUFFER_SIZE = 1000
CHANNEL_NAMES = ["ch1", "ch2", "ch3"]
COLS = ["t"] + CHANNEL_NAMES
N_CHANNELS = len(CHANNEL_NAMES)

WINDOW_SEC = 5.0  # last N seconds for
SLEEP_LOOP = 0.05


pg.setConfigOptions(useOpenGL=False)  # TODO acceleration OpenGL (to test)

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

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Dynamic Channels + Legend")

        layout = QVBoxLayout()

        # plot
        self.plot = pg.PlotWidget()
        # self.plot = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem()})
        # self.legend = self.plot.addLegend()

        # axis = pg.DateAxisItem()
        # axis.setFormat('%H:%M:%S')  # heures:minutes:secondes
        # self.plot = pg.PlotWidget(axisItems={'bottom': axis})



        # curves dict
        self.curves = {}

        for i, name in enumerate(CHANNEL_NAMES):
            curve = self.plot.plot(name=name)
            self.curves[name] = curve

        # checkboxes
        self.checkboxes = {}
        cb_layout = QHBoxLayout()

        for name in CHANNEL_NAMES:
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.stateChanged.connect(self.update_visibility)
            self.checkboxes[name] = cb
            cb_layout.addWidget(cb)

        # log
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        # buttons
        self.btn_start = QPushButton("Start")
        self.btn_pause = QPushButton("Pause")
        self.btn_stop = QPushButton("Stop")
        self.btn_kill = QPushButton("Kill")

        layout.addWidget(self.plot)
        layout.addLayout(cb_layout)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_kill)
        layout.addWidget(self.log)

        self.setLayout(layout)

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

        # timer
        self.timer = QTimer()
        # self.timer.timeout.connect(self.update_ui)
        self.timer.timeout.connect(self.update_ui_rolling)
        self.timer.start(30)

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

    def update_ui_rolling(self):
        while not self.queue.empty():
            self.log_msg(self.queue.get())

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


