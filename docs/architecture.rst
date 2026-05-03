Architecture
============

.. contents:: Sections
   :local:
   :depth: 2

Vue globale
-----------

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────────┐
   │  Processus principal (GUI)                                      │
   │                                                                 │
   │  ┌──────────────┐   signal data_ready(idx)   ┌──────────────┐  │
   │  │ DataWatcher  │ ─────────────────────────► │ MainWindow   │  │
   │  │  (QThread)   │   queued connection Qt      │  (QWidget)   │  │
   │  └──────┬───────┘                            └──────┬───────┘  │
   │         │ mp.Queue.get()                            │           │
   │         │                              shared mem read (zero-copy)
   └─────────┼─────────────────────────────────────────┼────────────┘
             │ mp.Queue.put(idx)            SharedMemory│(POSIX)
   ┌─────────┴─────────────────────────────────────────┴────────────┐
   │  Processus d'acquisition  (acq_worker — mp.Process)            │
   │  écrit timestamp + valeurs dans le buffer circulaire           │
   └─────────────────────────────────────────────────────────────────┘

Processus d'acquisition
-----------------------

:func:`~test_multi_process_pandas.main.acq_worker` tourne dans un
:class:`multiprocessing.Process` indépendant du thread GUI.

Il écrit dans un **buffer circulaire** de ``BUFFER_SIZE`` lignes
(défaut : 1 000) organisé ainsi :

.. list-table:: Format d'une ligne du buffer
   :header-rows: 1

   * - Colonne 0
     - Colonnes 1 … N
   * - Timestamp Unix (``time.time()``)
     - Valeurs des canaux (float64)

La position courante est ``pos = idx % BUFFER_SIZE``.
Le compteur ``idx`` est stocké dans ``meta[0]`` (mémoire partagée séparée).

Les données synthétiques générées sont :

- **ch1** : sin(idx × 0.1) + bruit
- **ch2** : cos(idx × 0.1) + bruit
- **ch3** : sin(idx × 0.05) + bruit

.. seealso:: :data:`~test_multi_process_pandas.main.BUFFER_SIZE`,
   :data:`~test_multi_process_pandas.main.SLEEP_LOOP`

Mémoire partagée
----------------

Deux segments :class:`multiprocessing.shared_memory.SharedMemory` POSIX
sont alloués par :class:`~test_multi_process_pandas.main.MainWindow` :

.. list-table::
   :header-rows: 1

   * - Segment
     - Taille
     - Contenu
   * - ``shm_data``
     - ``BUFFER_SIZE × (N_CHANNELS + 1) × 8`` octets
     - Buffer de données (float64)
   * - ``shm_meta``
     - ``2 × 8`` octets
     - ``meta[0]`` = index courant (int64)

Un :class:`pandas.DataFrame` ``df_view`` est créé comme **vue zero-copy**
sur ``shm_data`` via :func:`numpy.ndarray` avec ``buffer=shm_data.buf``.
Aucune copie n'est effectuée lors de la lecture.

.. warning::

   Les segments doivent être explicitement ``unlink()``-és à la fermeture
   (voir :meth:`~test_multi_process_pandas.main.MainWindow.closeEvent`).
   Un segment POSIX non unlinkné persiste au-delà du processus Python.

Thread DataWatcher
------------------

:class:`~test_multi_process_pandas.main.DataWatcher` est un
:class:`~PyQt6.QtCore.QObject` déplacé dans un :class:`~PyQt6.QtCore.QThread`
selon le pattern *worker object* de Qt.

.. code-block:: text

   main thread                    watcher thread
   ───────────                    ──────────────
   QThread.start()
        │
        └──► watcher.run()        bloque sur queue.get(timeout=0.1)
                                  dès qu'un idx arrive :
                                  data_ready.emit(idx)
                                       │
                    ◄──────────────────┘  queued connection → GUI thread

Le timeout de **100 ms** garantit que :meth:`~test_multi_process_pandas.main.DataWatcher.stop`
est honoré rapidement sans polling actif.

.. seealso:: :meth:`~test_multi_process_pandas.main.DataWatcher.run`,
   :meth:`~test_multi_process_pandas.main.MainWindow.closeEvent`

Affichage zero-copy
-------------------

:meth:`~test_multi_process_pandas.main.MainWindow.get_views` retourne
une ou deux vues :class:`pandas.DataFrame` sur ``df_view`` selon l'état
du buffer circulaire :

.. list-table::
   :header-rows: 1

   * - État du buffer
     - Retour
   * - Aucune donnée (idx = 0)
     - ``(None, None)``
   * - Buffer partiellement rempli (idx < BUFFER_SIZE)
     - ``(df_view[:idx], None)``
   * - Buffer plein
     - ``(df_view[pos:], df_view[:pos])`` — deux vues contiguës

:meth:`~test_multi_process_pandas.main.MainWindow.update_ui_rolling`
assemble les deux vues avec :func:`numpy.concatenate` (O(n) en temps,
mais sans copie des objets pandas) puis appelle ``setData`` sur les
courbes :class:`pyqtgraph.PlotDataItem`.

Interface utilisateur
---------------------

Le layout est défini dans ``views/main.ui`` (Qt Designer) et compilé
automatiquement en ``views/ui_main.py`` au démarrage via
:func:`~test_multi_process_pandas.main._compile_ui`.

:class:`~test_multi_process_pandas.main.MainWindow` hérite à la fois de
:class:`~PyQt6.QtWidgets.QWidget` et de ``Ui_MainWindow``
(*multiple inheritance pattern* Qt) pour accéder directement aux widgets
via ``self.btn_start``, ``self.plot``, etc.

Les icônes des boutons sont embarquées dans
``resources/icons/Boutons_rc.py`` (compilé depuis ``Boutons.qrc``).

.. list-table:: Boutons
   :header-rows: 1

   * - Bouton
     - Icône
     - Action
   * - Start
     - media-playback-start
     - :meth:`~test_multi_process_pandas.main.MainWindow.on_btn_start_clicked`
   * - Pause
     - media-playback-pause
     - :meth:`~test_multi_process_pandas.main.MainWindow.on_btn_pause_clicked`
   * - Stop
     - media-playback-stop
     - :meth:`~test_multi_process_pandas.main.MainWindow.on_btn_stop_clicked`
   * - Kill
     - process-stop
     - :meth:`~test_multi_process_pandas.main.MainWindow.on_btn_kill_clicked`
