#! /usr/env python
import os  # les données communes aux différents process
import logging
# import Outils.Init_user_python_path as import_up

rep_logging = os.path.join(os.path.expanduser('~'), 'Signaux', 'logs')

# pour détails cf. https://coralogix.com/blog/python-logging-best-practices-tips/

# TODO : remplacer (?) par une configuration dans un dict : "logging.config.dictConfig(config)"
# + config file en .yaml [import pyyaml module] (cf. https://zetcode.com/python/logging)


def define_loggings(rep_logging,
                    aff_format='%(asctime)s --  %(name)s -- %(processName)s -- %(threadName)s -- %(levelname)s -- %(message)s'):
    """[define 3 levels of logging in 3 separated files]

    Args:
        rep_logging ([str]): [path to logging files]
        aff_format (str, optional): [format of log]. Defaults to '%(asctime)s -- %(processName)s - %(threadName)s -- %(levelname)s -- %(message)s'.
    """
    import logging
    from logging.handlers import TimedRotatingFileHandler
    import os
    from collections import namedtuple
    from pythonjsonlogger import jsonlogger

    # loggers = namedtuple("loggers", 
    #         "Qt acq calcul moteur usb1608 wavelength_serial asserv")
    loggers = namedtuple("loggers", "Qt acq calcul  usb1608")

    # aff_format_info='%(asctime)s -- %(threadName)s -- %(levelname)s -- %(message)s'
    # aff_format_info='%(asctime)s -- %(threadName)s -- %(message)s'
    aff_format2 = "[%(asctime)s -- %(filename)s->%(funcName)s():%(lineno)d]%(levelname)s: %(message)s"
#     data_format = "[%(asctime)s -- name)s: %(message)s"

    formatter_debug = jsonlogger.JsonFormatter(aff_format)
    formatter_info = jsonlogger.JsonFormatter(aff_format)
    formatter_error = jsonlogger.JsonFormatter(aff_format)
    formatter_debugerror = jsonlogger.JsonFormatter(aff_format2)

    # formatter_moteur = jsonlogger.JsonFormatter("[%(asctime)s --  %(message)s")
    # formatter_data = jsonlogger.JsonFormatter("[%(asctime)s --  %(message)s")
    formatter_data = jsonlogger.JsonFormatter("[%(asctime)s")


    def define_logging(formatter, name="_log", when="s", interval=3600,
                       file_name="LOG.log"):
                       
        logger = logging.getLogger(name)
        # logger = logging.getLogger(__name__)
        handler = logging.handlers.TimedRotatingFileHandler(
                os.path.join(rep_logging, file_name),
                when=when, interval=interval, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    logger_acq = define_logging(formatter=formatter_debugerror,
                                name="acq_log", file_name="acq.log")

    logger_usb1608 = define_logging(formatter=formatter_debugerror,
                                    name="usb1608_log", file_name="usb1608.log")

    # logger_moteur = define_logging(formatter=formatter_moteur,
    #                                name="moteur_log", file_name="moteur.log")

    logger_qt = define_logging(formatter=formatter_debug,
                               name="Qt_log", file_name="Qt.log")

    logger_calcul = define_logging(formatter=formatter_info,
                                   name="calcul_log", file_name="calcul.log")

    # logger_wavelength_serial = define_logging(formatter=formatter_info,
    #                                name="wavelength_serial_log", file_name="wavelength_serial.log")

    # logger_asserv = define_logging(formatter=formatter_data,
    #                                name="asserv_log", file_name="asserv.log")

    # return loggers(logger_qt, logger_acq, logger_calcul, logger_moteur, 
    #                 logger_usb1608, logger_wavelength_serial, logger_asserv)


    return loggers(logger_qt, logger_acq, logger_calcul, logger_usb1608)

loggers = define_loggings(rep_logging)

loggers.Qt.setLevel(logging.INFO)  # défini niveau mini pour affichage
loggers.acq.setLevel(logging.INFO)  # défini niveau mini pour affichage
loggers.calcul.setLevel(logging.DEBUG)  # défini niveau mini pour affichage
# loggers.moteur.setLevel(logging.INFO)  # défini niveau mini pour affichage
loggers.usb1608.setLevel(logging.DEBUG)  # défini niveau mini pour affichage
# loggers.camera.setLevel(logging.INFO)  # défini niveau mini pour affichage
# loggers.camera_gui.setLevel(logging.DEBUG)  # défini niveau mini pour affichage
# loggers.wavelength_serial.setLevel(logging.DEBUG)  # défini niveau mini pour affichage

# loggers.asserv.setLevel(logging.INFO)   # les données d'asservissement
# The numeric values of logging levels are given in the following table :
# CRITICAL    50
# ERROR       40
# WARNING     30
# INFO        20
# DEBUG       10
# NOTSET      0
# aff_format_info='%(asctime)s -- %(threadName)s -- %(message)s'
