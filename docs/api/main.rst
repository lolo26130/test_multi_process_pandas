Module ``main``
===============

.. py:module:: test_multi_process_pandas.main

Ce module constitue le point d'entrée de l'application. Il regroupe le
worker d'acquisition, le pont Qt inter-thread et la fenêtre principale.

.. seealso:: :doc:`/architecture` pour la vue d'ensemble du flux de données.

Constantes
----------

.. autodata:: test_multi_process_pandas.main.BUFFER_SIZE
.. autodata:: test_multi_process_pandas.main.CHANNEL_NAMES
.. autodata:: test_multi_process_pandas.main.SLEEP_LOOP

Initialisation
--------------

.. autofunction:: test_multi_process_pandas.main._compile_ui

.. autofunction:: test_multi_process_pandas.main.main

Worker d'acquisition
--------------------

.. autofunction:: test_multi_process_pandas.main.acq_worker

Thread DataWatcher
------------------

.. autoclass:: test_multi_process_pandas.main.DataWatcher
   :members:
   :member-order: bysource
   :show-inheritance:

Fenêtre principale
------------------

.. autoclass:: test_multi_process_pandas.main.MainWindow
   :members:
   :member-order: bysource
   :show-inheritance:

   .. rubric:: Attributs principaux

   .. py:attribute:: curves
      :type: dict[str, pyqtgraph.PlotDataItem]
      :no-index:

      Dictionnaire ``{nom_canal: courbe}`` des courbes pyqtgraph.
      Voir :data:`~test_multi_process_pandas.main.CHANNEL_NAMES`.

   .. py:attribute:: df_view
      :type: pandas.DataFrame
      :no-index:

      Vue zero-copy sur ``shm_data``. Colonnes : ``["t", "ch1", "ch2", "ch3"]``.
      Voir :ref:`architecture:Mémoire partagée`.

   .. py:attribute:: watcher
      :type: DataWatcher
      :no-index:

      Instance du :class:`DataWatcher`, déplacée dans ``watcher_thread``.
      Voir :ref:`architecture:Thread DataWatcher`.
