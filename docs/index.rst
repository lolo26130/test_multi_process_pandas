test\_multi\_process\_pandas
============================

Démonstrateur d'acquisition temps-réel multi-processus avec affichage PyQtGraph.

.. rubric:: Vue d'ensemble

L'application illustre une architecture **producteur / consommateur
inter-processus** entièrement non-bloquante :

- un :ref:`processus d'acquisition <architecture:Processus d'acquisition>` écrit
  des données synthétiques dans un buffer circulaire en
  :ref:`mémoire partagée <architecture:Mémoire partagée>` ;
- un :ref:`thread DataWatcher <architecture:Thread DataWatcher>`
  surveille la queue de notification et émet un signal Qt ;
- le **thread GUI** reçoit le signal et rafraîchit les courbes
  :ref:`sans copie supplémentaire <architecture:Affichage zero-copy>`.

.. toctree::
   :maxdepth: 2
   :caption: Contenu

   architecture
   api/index

.. rubric:: Index et recherche

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
