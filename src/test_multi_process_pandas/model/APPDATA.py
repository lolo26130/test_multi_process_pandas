#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import numpy as np
from collections import namedtuple
import os
# import ctypes as ct
# from PyQt5.QtDBus import QDBusConnection
from enum import Enum, IntEnum

# -----------------------------------------------------------------------------
nTuple_sharedMem = namedtuple("SharedMemory", 
                            "mode mem_key index columns")
# -----------------------------------------------------------------------------
# Constants
CURSOR_UP = '\x1b[1A'
ERASE_LINE = '\x1b[2K'
CURSOR_BACK_2 = '\x1b[2D'
ERASE_TO_END_OF_LINE = '\x1b[0K'

GRAPH_LIB_pyqtgraph = True  # graph library choice
GRAPH_LIB_matplotlib = not GRAPH_LIB_pyqtgraph

os.environ["QDBUS_DEBUG"] = "0"  #   for debbuging DBUS transfers = "1" otherwise "0"

# =============================================================================
#   Config locale pour lecture nombres au clavier (QtGui.QDoubleValidator())
# =============================================================================
import locale  # noqa: E402
locale.setlocale(locale.LC_ALL, 'fr_FR.UTF-8')
# =============================================================================
#            Config mcc1608GX-2AO   for continuous analog in & out
# =============================================================================
# Parameters for AoDevice.a_out_scan
# from uldaq import (InterfaceType, AOutScanFlag, ScanOption, ScanStatus, 
#                         get_daq_device_inventory, DaqDevice)
try:
    from uldaq import ScanOption  # noqa: E402
    from uldaq import TriggerType  # noqa: E402
    # =============================================================================
    #                  Config processes names list launched by main GUI
    #             process name and index that complete the name at launch
    #         (to have a unique process name if multiple instances are launched)
    # =============================================================================
    name_process_acq, name_process_acq_index = "process_usb1608_QtDBus.py" , 1
    # name_process_motor, name_process_motor_index = "motor_cmd_QtDBus.py", 2 
except OSError as ose:
    print(f"no USB DAC ? {ose=}")
    name_process_acq, name_process_acq_index = None , 0  # i.e. no process  # TODO

    class ScanOption(IntEnum):
        CONTINUOUS = 1 << 3,
        #: Data conversions are controlled by an external clock signal.
        EXTTRIGGER = 1 << 5,
        #: Re-arms the trigger after a trigger event is performed.
        RETRIGGER = 1 << 6,
        #: Enables burst mode sampling, minimizing the channel skew.
    class TriggerType(IntEnum):
        NONE = 0,
        POS_EDGE = 1 << 0,
# =============================================================================
#                             USER Parameters :
# =============================================================================
#                           Pour modulation ao ( @ 10 000 Hz )
# =============================================================================
# mcc1608_ao_nCycles = 50  # 100 pour 333Hz   # 40
# mcc1608_ao_samples_per_cycle = 100==>100Hz    # 40==> 250Hz  # 30==>333.33Hz
#               we want xx samples per cycle ==> rate
mcc1608_ao_nCycles, mcc1608_ao_samples_per_cycle = 50, 57  # ==> 175Hz
# 50, 100 pour 100Hz  # 100, 30 pour 333.33Hz # 100, 40 pour 250Hz
# -----------------------------------------------------------------------------
#                Config SYNCHRONISATION : (EXTCLOCK)
# -----------------------------------------------------------------------------
EXTCLOCK = False # horloge d'acquisition interne mcc1608

if EXTCLOCK:
    mcc1608_scan_options = ScanOption.CONTINUOUS | ScanOption.EXTCLOCK
else:
    mcc1608_scan_options = ScanOption.CONTINUOUS #| ScanOption.EXTCLOCK
print(f"\nAttention {EXTCLOCK=}\n")


# -----------------------------------------------------------------------------
#                Config TRIGGER : (TriggerType)
# -----------------------------------------------------------------------------
TRIGGER = True  # declenchement par le scan du laser 
if TRIGGER:
    mcc1608_scan_options = mcc1608_scan_options | ScanOption.EXTTRIGGER | ScanOption.RETRIGGER
    mcc1608_trig_options = TriggerType.POS_EDGE
else:
    pass
print(f"\nAttention {TRIGGER=}\n")

# -----------------------------------------------------------------------------
#         if EXTCLOCK = True then scan rate is estimated (laser rate)
# -----------------------------------------------------------------------------
# if EXTCLOCK:
mcc1608_scan_rate = 10000.0  # Hz, (c_double convertible value)
print(f"Scan rate from laser clock estimated at : {mcc1608_scan_rate=} Hz\n")
mcc1608_ao_frequency = mcc1608_scan_rate / mcc1608_ao_samples_per_cycle  # fréquence de modulation du laser en Hz
print(f"so laser modulation frequency is estimated at : {mcc1608_ao_frequency=} Hz\n")
# -----------------------------------------------------------------------------
#         if EXTCLOCK = False then define scan rate internally
# -----------------------------------------------------------------------------
# if not EXTCLOCK:
#      mcc1608_ao_frequency = float(300)  # fréquence de modulation du laser en Hz
#      mcc1608_scan_rate = float(mcc1608_ao_frequency * 
#                     mcc1608_ao_samples_per_cycle)  # Hz, (c_double convertible value)
#      print(f"Laser modulation frequency defined at : {mcc1608_ao_frequency=} Hz")
#      print(f"So scan rate of mcc1608 clock is {mcc1608_scan_rate=} Hz")
# -----------------------------------------------------------------------------
mcc1608_ao_scan_rate = mcc1608_scan_rate # Hz, (c_double convertible value)
mcc1608_datasize_per_channel = mcc1608_ao_samples_per_cycle * mcc1608_ao_nCycles
print(f"{mcc1608_datasize_per_channel=} \n")
mcc1608_channels = np.array([0])  # list of used ai channels (must begin at 0)
# mcc1608_channels = np.array([0])  # list of used ai channels (must begin at 0)
mcc1608_ai_shape = (len(mcc1608_channels), mcc1608_datasize_per_channel)
mcc1608_full_datasize = np.prod(mcc1608_ai_shape)
mcc1608_cadence = mcc1608_full_datasize / mcc1608_scan_rate
print(f"{mcc1608_cadence=} s.\n")

# -----------------------------------------------------------------------------

# # =============================================================================
# #                        Graphs configs 
# # =============================================================================
N_MEASURES_DS = 100   # Nombre de mesures affichées
# N_MEASURES_ASSERV = 200  # 200 points on log_tab Moteur et asservissements (can be modified)


# =============================================================================
#               HARDWARE inputs amplitude configuration :
# =============================================================================
# mcc1608_low_channel = 0
# mcc1608_high_channel = 0
mcc1608_voltage_range_index = 3  # Use the first supported range # TODO in launch.py

# =============================================================================
#              to respect HARDWARE (mcc1608) limitations :
# =============================================================================
assert mcc1608_scan_rate <= 10**5
assert mcc1608_ao_scan_rate <= 10**5
# mcc1608_ao_samples_per_channel = int(2 * mcc1608_ao_scan_rate)  # 2 seconds buffer  
mcc1608_ao_samples_per_channel = mcc1608_ao_samples_per_cycle * 1  # only one cycle in memeory  
# =============================================================================

# =============================================================================
#                      Files configuration
# =============================================================================
mcc1608_datafile = None # (None or if dir exists : "/tmp/memory/test_process.hdf")
mcc1608_path_signaux = '/home/pi/Signaux/'  # stockage signaux bruts enregistrés
# =============================================================================
#                      Inter Processes Communication
# =============================================================================
mcc1608_stdio_event_string = "data_acquired"  # triggers graph drawing in main
# -----------------------------------------------------------------------------
#             memory sharing : for data acquisition (analog input):
# -----------------------------------------------------------------------------
mcc1608_mem_key = "mcc1608_pandas_data" #+ i
# -----------------------------------------------------------------------------
#      memory sharing : parameters for data generation (analog output) :
# -----------------------------------------------------------------------------
mcc1608_mem_key_ao = "mcc1608_ao_Data" 
mcc1608_ao_channels = np.array([0, 1])   # to be == hardware
mcc1608_mem_key_ao_keys = ['amplitude', 'offset', 'phase']
mcc1608_ao_key_ao_shape = (len(mcc1608_ao_channels),
                            len(mcc1608_mem_key_ao_keys))
mcc1608_ao_full_datasize = np.prod(mcc1608_ao_key_ao_shape)  # produit des dim
# -----------------------------------------------------------------------------
#                   shared memory for generated AO signal
# -----------------------------------------------------------------------------
mcc1608_mem_ao_signal = "mcc1608_ao_signal" 
mcc1608_ao_full_datasize_signal = (len(mcc1608_ao_channels) *
                                    mcc1608_ao_samples_per_channel)
mcc1608_ao_full_shape_signal = (mcc1608_ao_samples_per_channel,
                        len(mcc1608_ao_channels))
# # # -----------------------------------------------------------------------------
# #                             Echelles sliders etc.....
# # -----------------------------------------------------------------------------
# analog_out_amp_max = 0.1  # max sur slider horizontalSlider_AnalogOutput_amplitude_0
# analog_out_offset_max = 0.5 #  horizontalSlider_AnalogOutput_offset_0

# # =============================================================================

