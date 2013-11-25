# -*- coding: utf-8 -*-
"""
    sindri.tektronix.bertscope
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control the Tektronix BERTScope Bit Error Rate
    Analyzers.
    
    BERTScope Models:
    ===========================
    
        - BA1500
        - BA1600
        - BSA85C
        - BSA125A, BSA125B, BSA125C
        - BSA175C
        - BSA220C
        - BSA250C
        - BSA260C
        - BSA286C

    Sources::

        - Artek Incorporated `link <http://www.artek.co.jp/>`_
        - CLE1000 Software Operation Manual, CLE1000-S1-V1, firmware v1.1
          (rev. 1.2, July 2013)

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""

from lantz import Feat, DictFeat, Q_, Action
from sindri.mixins import IORateLimiterMixin, ErrorQueueInstrument
from lantz.network import TCPDriver
from lantz.serial import SerialDriver
from lantz.visa import SerialVisaDriver
from lantz.visa import GPIBVisaDriver
from lantz.errors import InstrumentError
from .common import ErrorQueueImplementation


class IEEE4882SubsetMixin(object):
    """IEEE 488.2 Command subset
    """
    @Feat(read_once=True)
    def idn(self):
        """Instrument identification.
        """
        # The *IDN? response is user configurable, so we must not try to parse.
        return self.query('*IDN?')
    
    @Action()
    def reset(self):
        """Set the instrument functions to the factory default power up state.
        """
        self.send('*RST')
        
    @Action()
    def wait(self):
        """Inhibit execution of an overlapped command until the execution of
        the preceding operation has been completed.
        """
        self.send('*WAI')
        
    @Feat()
    def status_byte(self):
        """Status byte, a number between 0-255.

        Decimal sum of the bits in the register.
        Bit #6: Master Summary Status Bit (MSS)
                This bit is set, if one of the bits in STB becomes true
                and the corresponding bit in the SRE is enabled.
        Bit #5: Event Summary Bit (ESB)
                This bit is set, if one of the bits in ESR becomes true
                and the corresponding bit in the ESE is enabled.
        Bit #4: Message Available Bit (MAV)
                This bit is set, if there is a message in the output buffer available.
        """
        return int(self.query('*STB?'))
    
    @Feat()
    def service_request_enabled(self):
        """Service request enable register.

        Decimal sum of the bits in the register.
        """
        return int(self.query('*SRE?'))
        
    @service_request_enabled.setter
    def service_request_enabled(self, value):
        return self.query("*SRE {0:d}".format(value))
    
    event_status_reg = Feat()

    @event_status_reg.setter
    def event_status_reg(self):
        """Queries the event register for the Standard Event Register group.
        
        Bits are cleared when read.
        """
        return int(self.query('*ESR?'))
        
    @Feat()
    def event_status_enabled(self):
        """Enables bits in the enable register for the Standard Event Register group.
        The selected bits are then reported to bit 5 of the Status Byte Register.

        Decimal sum of the bits in the register.
        Bit #7: Enable ESB when Power on or restart
        Bit #5: Enable ESB when a Command Error occur
        Bit #3: Enable ESB when a Device Dependent Error occur
        Bit #0: Enable ESB when Operation complete

        Others are not used.
        """
        return int(self.query('*ESE?'))

    @event_status_enabled.setter
    def event_status_enabled(self, value):
        self.query("*ESE {0:d}".format(value))

    @Action()
    def clear_status(self):
        """Clears the event registers in all register groups.
         Also clears the error queue.
        """
        self.send('*CLS')
        
    @Action()
    def wait_operation_complete_bit(self):
        """Returns 1 to the output buffer after all pending commands complete.

        Other commands cannot be executed until this command completes.
        """
        return self.query('*OPC?')
    
    @Action()
    def set_operation_complete_bit(self):
        """Sets "Operation Complete" (bit 0) in the Standard Event register at
        the completion of the current operation.

        The purpose of this command is to synchronize your application with the instrument.
        Other commands may be executed before Operation Complete bit is set.
        """
        return self.query('*OPC')
     
    @Feat(values={True: 0, False: 1})
    def poweron_status_clear_enabled(self):
        """Enables or disables clearing of two specific registers at power on:
        - Standard Event enable register
        - Status Byte condition register
        - Questionable Data Register
        - Standard Operation Register
        """
        return self.query('*PSC?')
    
    @poweron_status_clear_enabled.setter
    def poweron_status_clear_enabled(self, value):
        self.query("*PSC {}".format(value))
  

class Mainframe(object):
    """Tektronix BERTScope Mainframe Level Features
    """
    @Action()
    def run(self):
        """Start all systems within the BERTScope mainframe.
        """
        self.send("RST 1")
        
    @Action()
    def stop(self):
        """Stop all systems within the BERTScope mainframe.
        """
        self.send("RST 0")
    
    @Feat(values={True: 1, False: 0})
    def is_running(self):
        """
        """
        return int(self.query("RST?"))

    @Feat(units='s', limits=(0, 36E6))
    def run_duration(self):
        """The run duration of the BERTScope Analyzer.
        
        Setting to ``0`` is the equivalent of a GUI ``Clear``, which allows the 
        run to go on ``forever.``
        """
        return float(self.query("RDUR?"))
        
    @run_duration.setter
    def run_duration(self, value):
        self.send("RDUR {0}".format(value))
        
    #==========================================================================
    # ``VIEW`` control
    #==========================================================================
    __VIEWS = {'basic ber': 'BBER',
               'block error': 'BER',
               'burst length': 'BLEN',
               'ber contour': 'CONT',
               'correlation': 'CORR',
               'clock recovery control': 'CRC',
               'clock recovery service': 'CRS',
               'clock recovery loop response': 'CRLR',
               'detector': 'DET',
               'dpp': 'DPP',
               'editor': 'EDIT',
               'error free interval': 'EFIN',
               '2d error map': 'EMAP',
               'eye': 'EYE',
               'fec emulation': 'FEC',
               'generator': 'GEN',
               'home': 'HOME',
               'jitter peak': 'JITT',
               'jitter map': 'JMAP_MAP',
               'clock recovery jitter spectrum': 'JS',
               'jitter tolerance test': 'JTOL',
               'system event log': 'LOG',
               'lightwave test set interface': 'LTS',
               'mask test': 'MASK',
               'pattern sensitivity': 'PSEN',
               'q factor': 'QFAC',
               'strip chart': 'SCH',
               'clock recovery ssc waveform': 'SSCW',
               'stressed eye': 'STRESS',
               'system': 'SYST'
               }
    __VIEW_ALIASES = {'BERROR': 'BER',
                      'BLENGTH': 'BLEN',
                      'CONTOUR': 'CONT',
                      'CORRELATION': 'CORR',
                      'CRCONTROL': 'CRC',
                      'CRSERVICE': 'CRS',
                      'CRLOOPRESPONSE': 'CRLR',
                      'DETECTOR': 'DET',
                      'EDITOR': 'EDIT',
                      'EFINTERVAL': 'EFIN',
                      'GENERATOR': 'GEN',
                      'JITTER': 'JITT',
                      'JITTERSPECTRUM': 'JS',
                      'JTOLERANCE': 'JTOL',
                      'PSENSITIVITY': 'PSEN',
                      'QFACTOR': 'QFAC',
                      'SCHART': 'SCH',
                      'CRSSCWAVEFORM': 'SSCW',
                      'STRESSEDEYE': 'STRESS',
                      'SYSTEM': 'SYST'}
    
    @property
    def views(self):
        """A list of available views.
        """
        return list(self.__VIEWS.keys())
        
    @Feat(values=__VIEWS)
    def view(self):
        """The current view of the BERTScope Analyzer.
        """
        response = self.query("VIEW?")
        view = response.upper()
        if view in self.__VIEW_ALIASES:
            view = self.__VIEW_ALIASES[view]
        return view
        
    @view.setter
    def view(self, value):
        self.send("VIEW {0}".format(value))
    
    #==========================================================================
    @Feat(values={True: 1, False: 0})
    def gui_lockout_enabled(self):
        """The state of the GUI Lockout feature.
        """
        return int(self.query("GUIL?"))
        
    @gui_lockout_enabled.setter
    def gui_lockout_enabled(self, value):
        self.send("GUIL {0}".format(value))
        
    @Action()
    def get_internal_temperature(self):
        """Retrieve internal temperature in degrees Celsius. 
        
        This measurement is not calibrated, and should only be used as a 
        relative indication of temperature. 
        """
        return Q_(float(self.query("SENS:TEMP?")), 'celsius')
        
    @Feat(values={True: 1, False: 0})
    def detector_delay_needs_recalibration(self):
        """Whether or not the detector delay needs recalibration.
        
        **NOTE:**
        Because monitoring for these calibrations is suspended while Physical 
        Layer tests are running, using this command under those circumstances 
        might not return an accurate result.
        """
        return int(self.query("DELAY:DETR?"))
        
    @Feat(values={True: 1, False: 0})
    def generator_delay_needs_recalibration(self):
        """Whether or not the detector delay needs recalibration.
        
        **NOTE:**
        Because monitoring for these calibrations is suspended while Physical 
        Layer tests are running, using this command under those circumstances 
        might not return an accurate result.
        """
        return int(self.query("DELAY:GENR?"))


class Detector(object):
    """Tektronix BERTScope Detector Level Features
    """
    @Feat(units='picoseconds')
    def detector_data_delay(self):
        """The data delay for the error detector.
        """
        return float(self.query("DET:DDEL?"))
        
    @detector_data_delay.setter
    def detector_data_delay(self, value):
        self.send("DET:DDEL {0}".format(value))
    
    @Feat(values={True: 1, False: 0})
    def detector_auto_align_succeeded(self):
        """Whether or not the last data centering (auto-align) succeeded.
        """
        return int(self.query('DET:DCS?'))
    
    @Action()
    def detector_auto_align(self):
        """Performs an ``auto-align``, or data centering, for the error detector.
        
        :returns: Success state of the auto-alignment.
        :type bool:
        """
        self.send('DET:PDC')
        return self.detector_auto_align_succeeded
        
    @Action()
    def detector_reset_results(self):
        """Reset the error detector results.
        """
        self.send("DET:RRES")
        
    @Action()
    def get_detector_bit_count(self):
        """The total number of bits detected during the run.
        """
        return Q_(float(self.query("DET:BITS?")), 'bits')
        
    @Action()
    def get_detector_error_count(self):
        """The total number of errors detected during the run.
        """
        return Q_(float(self.query("DET:ERR?")), 'bits')
        
    @Action()
    def get_detector_bit_error_rate(self):
        """The computed bit error rate for the detector, based on run results.
        """
        return float(self.query("DET:BER?"))
    
    @Action()
    def get_detector_elapsed_time(self):
        """Retrieve the elapsed time since last reset.
        """
        return Q_(float(self.query("DET:ETIM?")), 'seconds')
        
    @Action()
    def get_detector_resyncs(self):
        """Retrieve how many resyncs the detector has tried during run.
        """
        return int(self.query("DET:RESY?"))
        
    @Action()
    def get_detector_error_free_bits_count(self):
        """Retrieve the latest count of error free bits.
        """
        return Q_(float(self.query("DET:EFB?")), 'bits')
        
    @Action()
    def get_detector_error_free_time(self):
        """Retrieve the latest error free time.
        """
        return Q_(float(self.query("DET:EFT?")), 'seconds')
    
    __BER_DISPLAY_MODES = {'accumulation': 'TACC',
                           'interval': 'INT'}
                           
    __BER_DISPLAY_MODES_ALIASES = {'TACCUMULATION': 'TACC',
                                   'INTERVAL': 'INT'}    
    
    @Feat(values=__BER_DISPLAY_MODES)
    def detector_ber_display_mode(self):
        """The detector BER display mode.
        
        .. seealso: detector_ber_display_modes
        """
        response = self.query("DET:BDM?")
        mode = response.upper()
        if mode in self.__BER_DISPLAY_MODES_ALIASES:
            mode = self.__BER_DISPLAY_MODES_ALIASES[mode]
        return mode
    
    @detector_ber_display_mode.setter
    def detector_ber_display_mode(self, value):
        self.send("DET:BDM {0}".format(value))
    
    @Feat(units='seconds')
    def detector_update_interval(self):
        """The detector’s results update interval.
        
        This will take effect when the BER display mode is set to ``interval``
        instead of ``accumulation``.
        """
        return float(self.query("DET:RUIN?"))
    
    @detector_update_interval.setter
    def detector_update_interval(self, value):
        self.send("DET:RUIN {0}".format(value))


class BERTScope(object):
    """Tektronix BERTScope Bit Error Rate Analyzer Core Features
    
    **NOTE:**
    Any commands the BERTScope software doesn’t understand are sent to the 
    Clock Recovery software, which then controls the clock recovery instrument.

    If more than one BERTScope CR is connected to the BERTScope or host 
    computer, the remote control software will not connect automatically. 
    In this case, the Remote computer must issue a NAMES? query to discover 
    the IDs of the connected BERTScope CRs, and OPEN the one desired before 
    issuing control commands. If the Remote computer needs to control multiple 
    BERTScope CRs, it would OPEN, control, then CLOSE one, then OPEN, control, 
    and CLOSE another. The device that is OPEN is referred to as the “current” 
    device throughout this document.  
    
    .. seealso: BERTScope Remote Control Guide, Part Number 0150-703-06.
    """    
    @Feat(read_once=True)
    def scpi_version(self):
        """Returns the SCPI revision to which the instrument complies.

        :returns: SCPI version.
        :type: str
        
        The returned value is of a string in the form YYYY.V where the “Y’s” 
        represent the year of the version, and the “V” represents a version 
        number for that year (for example, 1995.0).
        """
        return self.query('SYST:VERS?')
    
    #==========================================================================
    # ``STATus`` sub-system
    #==========================================================================


class BERTScope_TCP(BERTScope, Mainframe, Detector,
                 ErrorQueueImplementation, 
                 ErrorQueueInstrument, IEEE4882SubsetMixin,
                 IORateLimiterMixin, TCPDriver):
    """Tektronix BERTScope TCP Driver
    """
    #: Encoding to transform string to bytes and back as defined in
    #: http://docs.python.org/py3k/library/codecs.html#standard-encodings
    ENCODING = 'latin1'  # some funky characters this way come.

