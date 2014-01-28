# -*- coding: utf-8 -*-
"""
    sindri.agilent.e363xa
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control an HP/Agilent E363xA Series Power Supply

    E363xA Series::
    
        - Agilent/HP E3631A
        - Agilent/HP E3632A
        - Agilent/HP E3633A
        - Agilent/HP E3634A

    Sources::

        - Agilent Technologies `link <http://www.agilent.com>`_

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


def scrub_string_for_display(value):
    """Remove non-displayable and dangerous chars from text string
    
    :param value: The string to sanitize
    :type value: str
    """
    _sanitized = ''.join([c for c in value if (31 < ord(c) < 128)])
    # properly escape quotations
    _sanitized = _sanitized.replace('"', '``')
    return _sanitized


class IEEE4882SubsetMixin(object):
    """IEEE 488.2 Command subset
    """
    @Feat(read_once=True)
    def idn(self):
        """Instrument identification.
        """
        return self.parse_query('*IDN?', 
                format='{manufacturer:s},{model:s},{serialno:s},{softno:s}')
    
    @Action()
    def reset(self):
        """Set the instrument functions to the factory default power up state.
        """
        self.send('*RST')
    
    @Action()
    def self_test(self):
        """Performs a complete instrument self-test.

        If test fails, one or more error messages will provide additional information.
        When available, Use SYSTem:ERRor? to read error queue.
        """
        return self.query('*TST?') == '0'
        
    @Action()
    def wait(self):
        """Inhibit execution of an overlapped command until the execution of
        the preceding operation has been completed.
        """
        self.send('*WAI')
        
    @Action()
    def trigger(self):
        """Equivalent to Group Execute Trigger.
        """
        self.send('*TRG')
        
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
        Register is read-only; bits not cleared when read.
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
        
    @Action(limits=(1,3,1))
    def recall_state(self, location=1):
        """This command recalls a previously stored state. 
        
        To recall a stored state, you must use the same memory location used 
        previously to store the state. You recall *RST states or values of the 
        power supply from a memory location that was not previously specified 
        as a storage location.
        """
        self.send("*RCL {}".format(location))
    
    @Action(limits=(1,3,1))
    def save_state(self, location=1):
        """This command stores the present state of the power supply. 
        
        Three memory locations (numbered 1, 2 and 3) are available to store 
        operating states of the power supply. The state storage feature 
        ``remembers`` the states or values of ``selected_instrument``, 
        ``voltage`` for that instrument, ``current`` for that instrument, 
        ``output_enabled``, ``output_tracking``, ``trigger_source``, and 
        ``trigger_delay``. 
        
        To recall a stored state, you must use the same memory location used 
        previously to store the state.
        """
        self.send("*SAV {}".format(location))


class E3631A(object):
    """HP/Agilent E3631A Triple Output DC Power Supply
    
    Example Usage:

    Basic Usage
    ===========
    ::    
        ...
        >>>inst.idn  # the details on the following line will be omitted for example.
        OrderedDict(...)
        >>>inst.auto_dequeue_error_enabled  #defaults to False
        False
        >>>inst.output_enabled = False
        >>>inst.dequeue_error()  # will raise any error as an ``InstrumentError``
        >>>inst.outputs
        ['', 'P25V', 'P6V', 'N25V']
        >>>inst.voltage['P6V'] = 3.31  # changes without enabling output
        >>>inst.dequeue_error()
        >>>inst.current['P6V'] = 0.5  # changes without enabling output
        >>>inst.dequeue_error()
        >>>inst.output_enabled = True
        >>>inst.dequeue_error()
        >>>inst.measure_current('P6V')
        >>>inst.dequeue_error()
        >>>inst.measure_voltage('P25V')
        >>>inst.dequeue_error()
    
    Automatic Error Dequeueing
    ==========================
    ::
        ...
        >>>inst.reset()  # ``*RST``
        >>>inst.clear_status()  # ``*CLS``
        >>>inst.auto_dequeue_error_enabled = True
        >>>inst.auto_dequeue_error_delay  # time to wait before attempting dequeue
        <Quantity(1.0, 'second')>
        >>>inst.output_enabled = True  # with a 1.0 delay before dequeue, after send.
        >>>inst.voltage['P6V']  # composite commands will take longer at first
        <Quantity(0.0, 'volt')>
        >>>inst.output_enabled  # queries will complete atomically first, then dequeue
        True
    
    Input Modes
    ===========
    ::
        ...
        >>>inst.input_modes
        ['lockout', 'remote', 'local']
        >>>inst.set_input_mode('local')
        >>>inst.set_input_mode('remote')
    
    Stored States
    =============
    ::
        ...
        >>>inst.save_state()  # defaults to location 1
        >>>inst.recall_state(2)
        >>>inst.recall_state()  # defaults to location 1
        >>>inst.store()  # same as ``save_state()``
    
    Software IO Flow Rate Control
    =============================
    ::
        ...
        >>>inst.io_min_delta
        <Quantity(0.0, 'second')>
        >>>inst.io_min_delta = 0.033  # 33 ms delta between IO operations
        >>>inst.idn  # queries always wait at first, as they are send + receive
        >>>inst.voltage['P6V'] = 3.31  # compound commands have mult. waits
        >>>inst.io_min_delta = 3.0  # 3 second delta
        >>>import time
        >>>inst.reset(); inst.clear_status()  # notice the wait between
        >>>time.sleep(3.5)  # 3.5 second pause here...
        >>>inst.reset()  # notice the lack of a wait, the delta is not naive
        
    
    
    **NOTE**: In the above examples, if an error occurred and is dequeued, it will
    be raised as an ``InstrumentError``.
    
    Sources::
    
        - Agilent E3631A Manual (P/N: E3631A-90002, July 2013)
    
    """
    __INPUT_MODES = {'local': 'LOC', 'remote': 'REM', 'lockout': 'RWL'}
    __TRIGGER_SOURCES = {'immediate': 'IMM', 'bus': 'BUS'}
    # in the following list, the zeroeth element MUST be the ``default`` key!
    __SOURCES = {'': None, 'P6V': 'P6V', 'P25V': 'P25V', 'N25V': 'N25V'}  # default, +6V, +25V, -25V
        
    def initialize(self, *args, init_input_mode='remote', **kwargs):  
        try:        
            _retval = super().initialize(*args, **kwargs)
        except:
            raise
        #else:
        # prevent unexpected behavior w/ remote control!
        self.set_input_mode(init_input_mode)
        return _retval
    
    @property
    def input_modes(self):
        """The available input modes.
        
        - ``local``: ALL front panel keys are functional.
        - ``remote``: All front panel keys, EXCEPT ``Local`` key, are disabled.
        - ``lockout``: All front panel keys, INCLUDING ``Local`` key, are disabled.
        
        :return: list of available input modes
        :type list:
        """
        return list(self.__INPUT_MODES.keys())
    
    @Action(values=__INPUT_MODES)
    def set_input_mode(self, value):
        """Put the instrument into the specified input mode (default=``remote``)
        
        See ``input_modes`` for a detailed list of available modes.
        """
        self.send("SYST:{}".format(value))
    
    @property
    def outputs(self):
        """The available output (source) channels.
        
        Empty string uses the currently selected instrument/output.
        See the member/feature called ``selected_instrument``.
        
        :return: list of available outputs
        :type list:
        """
        return list(self.__SOURCES.keys())
    
    @property
    def trigger_sources(self):
        """The available trigger event sources.
        
        :return: list of available trigger event sources
        :type list:
        """
        return list(self.__TRIGGER_SOURCES.keys())
    
    #alias    
    @Action(limits=(1,3,1))
    def store(self, location=1):
        """Stores the current instrument state for future recall.
        
        This action is an alias for the ``save_state`` action. 
        
        .. seealso: save_state
        """
        self.save_state(location)
    
    @Action()
    def beep(self):
        """Generate a beep sound from the instrument.
        """
        self.send('SYST:BEEP')
    
    @Feat(read_once=True)
    def scpi_version(self):
        """The present SCPI version for the power supply.
        
        The returned value is of a string in the form YYYY.V where the “Y’s” 
        represent the year of the version, and the “V” represents a version 
        number for that year (for example, 1995.0).
        """
        return self.query('SYST:VERS?')
    
    @Feat(values={True: 1, False: 0})
    def output_enabled(self):
        """Enabled state of ALL of the power supply outputs.
        """
        return int(self.query('OUTP?'))
    
    @output_enabled.setter
    def output_enabled(self, value):
        self.send('OUTP {}'.format(value))
    
    @Feat(values={True: 1, False: 0})
    def tracking_enabled(self):
        """Enabled state of output tracking (P25V & N25V source channels)
        """
        return int(self.query('OUTP:TRAC?'))
    
    @tracking_enabled.setter
    def tracking_enabled(self, value):
        self.send('OUTP:TRAC {}'.format(value))
    
    @Feat(values=__TRIGGER_SOURCES)
    def trigger_source(self):
        """The selected trigger source for the power supply
        
        When immediate, the trigger event is dispatched by issuing an
        ``initiate`` command (program-level). When listening to the bus, the
        trigger even is dispatched by using the *TRG (G.E.T.) bus-level
        commands. The choices ARE mutually exclusive.
        
        See member ``trigger_sources`` for a list of trigger sources.
        """
        return self.query('TRIG:SOUR?')
    
    @trigger_source.setter
    def trigger_source(self, value):
        self.send('TRIG:SOUR {}'.format(value))
    
    @Feat(units='s', limits=(0, 3600))
    def trigger_delay(self):
        """Time from trigger event to trigger action (seconds), programmable.
        """
        return self.query('TRIG:DEL?')
    
    @trigger_delay.setter
    def trigger_delay(self, value):
        self.send('TRIG:DEL {}'.format(value))
    
    @Action()
    def trigger_initiate(self):
        """Initiate trigger subsystem (BUS)/Dispatch trigger event (IMMEDIATE)
        
        This command causes the trigger system to initiate. This command
        completes one full trigger cycle when the trigger source is an 
        immediate and initiates the trigger subsystem when the trigger 
        source is bus.
        """
        self.send('INIT')
    
    @Feat(values=__SOURCES)
    def selected_instrument(self):
        """The sub-system/sub-instrument to which any general commands will apply.
        
        For example, if ``inst.voltage = 3.31`` is executed, then the targeted
        subsystem/instrument/output channel will be whichever instrument
        is currently selected.
        
        See the ``outputs`` member for a list of available output channels.
        """
        return self.query('INST:SEL?')        
    
    @selected_instrument.setter
    def selected_instrument(self, value):
        self.send('INST:SEL {}'.format(value))    
     
    @DictFeat(units='V', keys=__SOURCES)
    def voltage(self, key=''):
        """The immediate voltage level (unit := ``V``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``inst.voltage['P25V'] = 3.31``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        NOTE: The output MUST be enabled before attempting to SET an output
        voltage!
        
        :raises: OutputDisabledError
        
        .. seealso: ``outputs`` for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        return self.query('SOUR:VOLT:LEV:IMM:AMPL?')
    
    @voltage.setter
    def voltage(self, key='', value=None):
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        if value is not None:
            self.send('SOUR:VOLT:LEV:IMM:AMPL {}'.format(value))
    
    @DictFeat(units='V', keys=__SOURCES, read_once=True)
    def min_voltage(self, key=''):
        """The minimum voltage level (unit := ``V``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``min_v = inst.min_voltage['P25V']``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        self.send('SOUR:VOLT:LEV:IMM:AMPL? MIN')    
    
    @DictFeat(units='V', keys=__SOURCES, read_once=True)
    def max_voltage(self, key=''):
        """The maximum voltage level (unit := ``V``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``min_v = inst.max_voltage['P25V']``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        self.send('SOUR:VOLT:LEV:IMM:AMPL? MAX')
    
    @DictFeat(units='A', keys=__SOURCES)
    def current(self, key=''):
        """The immediate current LIMIT level (unit := ``A``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``inst.current['P25V'] = 1.0``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        return self.query('SOUR:CURR:LEV:IMM:AMPL?')
    
    @current.setter
    def current(self, key='', value=None):
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        if value is not None:
            self.send('SOUR:CURR:LEV:IMM:AMPL {}'.format(value))

    @DictFeat(units='V', keys=__SOURCES, read_once=True)
    def min_current(self, key=''):
        """The minimum current LIMIT level (unit := ``A``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``min_c = inst.min_current['P25V']``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        self.send('SOUR:CURR:LEV:IMM:AMPL? MIN')    
    
    @DictFeat(units='V', keys=__SOURCES, read_once=True)
    def max_current(self, key=''):
        """The maximum current LIMIT level (unit := ``A``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``max_c = inst.max_current['P25V']``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        self.send('SOUR:CURR:LEV:IMM:AMPL? MAX')
    
    @DictFeat(units='V', keys=__SOURCES)
    def triggered_voltage(self, key=''):
        """The voltage level that will be actuated on trigger (unit := ``V``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``inst.triggered_voltage['P25V'] = 3.31``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        return self.query('SOUR:VOLT:LEV:TRIG:AMPL?')
        
    @triggered_voltage.setter
    def triggered_voltage(self, key='', value=None):
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        if value is not None:
            self.send('SOUR:VOLT:LEV:TRIG:AMPL {}'.format(value))
        
    @DictFeat(units='A', keys=__SOURCES)
    def triggered_current(self, key=''):
        """Current LIMIT level that will be actuated on trigger (unit := ``A``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``inst.triggered_current['P25V'] = 1.0``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        return self.query('SOUR:CURR:LEV:TRIG:AMPL?')
        
    @triggered_current.setter
    def triggered_current(self, key='', value=None):  # self, key='', value
        if key != self.__SOURCES['']:
            self.selected_instrument = key
        if value is not None:
            self.send('SOUR:CURR:LEV:TRIG:AMPL {}'.format(value))

    @Action(values=__SOURCES)
    def measure_voltage(self, value=''):
        """Measure the voltage level at the output port (unit := ``V``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``volts = inst.measure_voltage['P25V']``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if value != self.__SOURCES['']:
            self.selected_instrument = value
        _magnitude = self.query('MEAS:VOLT?')
        return Q_(_magnitude, 'V')  # Volts
        
    @Action(values=__SOURCES)
    def measure_current(self, value=''):
        """Measure the current level at the output port (unit := ``A``)
        
        The targeted output channel/sub-system can be specified as follows:
        - ``amps = inst.measure_current['P25V']``
        
        If no target is given, then the currently selected output/instrument 
        is assumed, and no selection change is made.
        
        See the ``outputs`` member for a list of available output channels.
        """
        if value != self.__SOURCES['']:     
            self.selected_instrument = value
        _magnitude = self.query('MEAS:CURR?')
        return Q_(_magnitude, 'A')  # Amps

    @Feat(values={True: 1, False: 0})
    def display_enabled(self):
        """Turn on/off the display. Only guaranteed to work in ``remote`` mode.
        """
        return int(self.query('DISP:WIND:STAT?'))
        
    @display_enabled.setter
    def display_enabled(self, value):
        self.send("DISP:WIND:STAT {}".format(value))
    
    # pay attention here... this matters.
    _GET_DISPLAY_TEXT_PROC = None
    _SET_DISPLAY_TEXT_PROC = scrub_string_for_display
    _GETP_SETP_DISPLAY_TEXT = (_GET_DISPLAY_TEXT_PROC, _SET_DISPLAY_TEXT_PROC)
    @Feat(procs=(_GETP_SETP_DISPLAY_TEXT, ))
    def display_text(self):
        """The text to be displayed on the front panel display
        
        NOTE: The text string will be ``sanitized`` before tranmission.
        Therefore, the string which is returned may differ from the string
        which was sent!
        """
        return self.query('DISP:WIND:TEXT:DATA?').strip('"')
        
    @display_text.setter
    def display_text(self, value):
        self.send("DISP:WIND:TEXT:DATA \"{0}\"".format(value))
    
    @Action()
    def clear_display_text(self):
        """Remove the textual message, and show standard display
        """
        self.send('DISP:WIND:TEXT:CLE')

    def finalize(self, *args, **kwargs):
        try:
            # return the front panel to user control
            self.set_input_mode('local')
        except:
            pass
        finally:
            super().finalize(*args, **kwargs)
            
    def __del__(self):
        self.finalize()


class E3631A_TCP(E3631A, ErrorQueueImplementation, 
                 ErrorQueueInstrument, IEEE4882SubsetMixin, 
                 IORateLimiterMixin, TCPDriver):
    pass
    

class E3631A_Serial(E3631A, ErrorQueueImplementation, 
                    ErrorQueueInstrument, IEEE4882SubsetMixin, 
                    IORateLimiterMixin, SerialDriver):
    ENCODING = 'ascii'

    RECV_TERMINATION = '\r\n'
    SEND_TERMINATION = '\r\n'
    
    #: -1 is mapped to get the number of bytes pending.
    RECV_CHUNK = -1

    #: communication parameters
    BAUDRATE = 9600
    BYTESIZE = 8
    PARITY = 'none'
    STOPBITS = 1

    #: flow control flags
    RTSCTS = False
    DSRDTR = False
    XONXOFF = False

