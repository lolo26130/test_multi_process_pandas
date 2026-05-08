"""Tests du canal de notification D-Bus : acq_worker → MainWindow.

Le canal de notification utilise D-Bus depuis que DataWatcher (polling mp.Queue)
a été remplacé. Ces tests vérifient que QDBusConnection.sessionBus() est
disponible et que MainWindow s'y connecte correctement.
"""
from PyQt6.QtDBus import QDBusConnection

from test_multi_process_pandas.main import _DBUS_PATH, _DBUS_IFACE, _DBUS_SIG


class TestDBusAvailability:

    def test_session_bus_connected(self):
        """Le session bus D-Bus est accessible depuis le processus de test."""
        assert QDBusConnection.sessionBus().isConnected()

    def test_mainwindow_connects_to_dbus(self, win):
        """MainWindow s'abonne au signal D-Bus sans erreur au démarrage."""
        # Si le bus est disponible, on_data_ready doit être connecté —
        # on vérifie indirectement que __init__ n'a pas loggé d'erreur D-Bus.
        log_text = win.log.toPlainText()
        assert "DBUS" not in log_text, \
            f"Erreur D-Bus dans le log : {log_text!r}"

    def test_dbus_constants_are_valid_paths(self):
        """Les constantes de routage D-Bus respectent les conventions de nommage."""
        assert _DBUS_PATH.startswith("/"), "path D-Bus doit commencer par /"
        assert "." in _DBUS_IFACE, "interface D-Bus doit contenir un point"
        assert _DBUS_SIG.isidentifier(), "nom du signal doit être un identifiant"
