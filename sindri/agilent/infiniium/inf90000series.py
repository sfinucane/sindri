# -*- coding: utf-8 -*-
"""
    sindri.agilent.infiniium.inf90000series
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control an Agilent Infiniium 90K Series Devices

    N77XX Series::
    
        - DSAX92504A Digital Signal Analyzer (oscilloscope)
        - There are others... please write drivers!

    Sources::

        - Agilent Technologies `link <http://www.agilent.com>`_
        - Agilent Infiniium 90000 Series Oscilloscopes Programmer's Reference (v04.50.0000, May 2013)

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""

import struct
from copy import deepcopy
from lantz import Feat, DictFeat, Q_, Action
from sindri.mixins import IORateLimiterMixin, ErrorQueueInstrument
from lantz.network import TCPDriver
from lantz.errors import InstrumentError
from sindri.errors import UnexpectedResponseFormatError
from sindri.ieee4882.arbitrary_block import read_definite_length_block
from ..common import ErrorQueueImplementation
from ...mixins import Verifiable

class IEEE4882SubsetMixin(object):

    @Feat(read_once=True)
    def idn(self):
        """Instrument identification.
        """
        return self.parse_query('*IDN?',
                format='{manufacturer:s},{model:s},{serialno:s},{softno:s}')

    @Feat(read_once=True)
    def fitted_options(self):
        """Fitted options.
        """
        return self.query('*OPT?').split(',')

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
        return self.query('*SRE {0:d}', value)

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
        self.query('*ESE {0:d}', value)

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
        self.query('*PSC {}'.format(value))

    @Action()
    def recall_state(self, location):
        """Recalls (*RCL) instrument state in specified non-volatile location.

        :param location: non-volatile storage location.
        """
        self.send('*RCL {}'.format(location))

    @Action()
    def save_state(self, location):
        """Saves instrument state in specified non-volatile location.

        Previously stored state in location is overwritten (no error is generated).
        :param location: non-volatile storage location.
        """
        self.send('*SAV'.format(location))


class ValidityState(object):
    """An Infiniium 90000 Series oscilloscope measurement validity state.
    """
    __code = None
    __valid = False
    __description = None
    
    validity_code_descriptions = (
        {0: 'Result correct. No problem found.',
         1: 'Result questionable but could be measured.',
         2: 'Result less than or equal to value returned.',
         3: 'Result greater than or equal to value returned.',
         4: 'Result returned is invalid.',
         17: 'Result invalid. Completion criteria not reached.'} )
    
    def __init__(self, code):
        """Initialize the result validity state instance.
        
        The code given should be the integer code returned as the validity
        state of a given measurement from the instrument.
        
        :param: code
        :type int:
        """
        if not (0 <= code <= 46):
            raise ValueError('Validity state code must be in [0, 46].')
            
        self.__code = code
        if self.__code < 4:
            self.__valid = True
        
        desc_index = code if code in self.validity_code_descriptions else 4    
        self.__description = self.validity_code_descriptions[desc_index]
        
    @property
    def code(self):
        return deepcopy(self.__code)
        
    @property
    def is_valid(self):
        return deepcopy(self.__valid)
        
    @property
    def description(self):
        return deepcopy(self.__description)


class MeasurementResult(Verifiable):
    """An Infiniium 90000 Series oscilloscope measurement result.
    """
    __label = None
    __current = None
    __max = None
    __min = None
    __mean = None
    __stddev = None
    __meas_count = None
    __range = None
    
    __validity_state = None
    __valid = None  # tri-state validity, because it is possible to not know.
    
    def __init__(self, label, results):
        """Initialize the measurement result instance.

        The label should probably be a string, but can be any type which
        supports encoding to bytes.
        
        The result should be the measurement statistics, validity state, etc.

        :param: label
        :type str:
        
        :param: results
        :type dict:
        """
        super().__init__()
        chksum_data = b'#'  # sort of a ``salt``
        self.__utc_stamp = self.generate_timestamp()
        
        self.__label = label
        chksum_data += label.encode()
        
        if 'current' in results:
            self.__current = float(results['current'])
            chksum_data += struct.pack('!f', self.__current)
        if 'maximum' in results:
            self.__max = float(results['maximum'])
            chksum_data += struct.pack('!f', self.__max)
        if 'minimum' in results:
            self.__min = float(results['minimum'])
            chksum_data += struct.pack('!f', self.__min)
        if 'mean' in results:
            self.__mean = float(results['mean'])
            chksum_data += struct.pack('!f', self.__mean)
        if 'standard deviation' in results:
            self.__stddev = float(results['standard deviation'])
            chksum_data += struct.pack('!f', self.__stddev)
        if 'measurement count' in results:
            self.__meas_count = float(results['measurement count'])
            chksum_data += struct.pack('!f', self.__meas_count)
        if 'validity state' in results:
            self.__validity_state = ValidityState(int(results['validity state']))
            self.__valid = self.__validity_state.is_valid
            chksum_data += struct.pack('!?', self.__valid)
        # range is computed value:
        if (self.__max is not None) and (self.__min is not None):
            self.__range = (self.__max - self.__min)
            chksum_data += struct.pack('!f', self.__range)
                        
        self.__checksum = self.compute_checksum(chksum_data)
        
    @property
    def label(self):
        return deepcopy(self.__label)
    
    @property
    def current(self):
        return deepcopy(self.__current)
        
    @property
    def max(self):
        return deepcopy(self.__max)
        
    @property
    def min(self):
        return deepcopy(self.__min)
        
    @property
    def mean(self):
        return deepcopy(self.__mean)
        
    @property
    def standard_deviation(self):
        return deepcopy(self.__stddev)
        
    @property
    def measurement_count(self):
        return deepcopy(self.__meas_count)
        
    @property
    def range(self):
        return deepcopy(self.__range)
        
    @property
    def is_valid(self):
        return deepcopy(self.__valid)


class Infiniium90000(object):
    """Agilent Infiniium 90000 Series Universal Features
    """
    __MEAS_STATS = {'all': 'ON', 'current': 'CURR', 'maximum': 'MAX',
                    'minimum': 'MIN', 'mean': 'MEAN',
                    'standard deviation': 'STDD'}

    @property
    def measurement_statistics(self):
        """The list of available measurement statistic selection options
        
        - ``all`` := all of the following statistics are returned.
        - ``current`` := ONLY the ``current`` value
        - ``maximum`` := ONLY the maximum value
        - ``minimum`` := ONLY the minimum value
        - ``mean`` := ONLY the mean value
        - ``standard deviation`` := ONLY the standard deviation       
        
        .. seealso: selected_measurement_statistic
        """
        return list(self.__MEAS_STATS.keys())
    
    @Feat(values=__MEAS_STATS)
    def selected_measurement_statistic(self):
        """The type of information (statistics) returned from ``get_displayed_results``.
        
        The following values for this feature are case sensitive:
            - ``all`` := all of the following statistics are returned.
            - ``current`` := ONLY the ``current`` value
            - ``maximum`` := ONLY the maximum value
            - ``minimum`` := ONLY the minimum value
            - ``mean`` := ONLY the mean value
            - ``standard deviation`` := ONLY the standard deviation
        """
        return self.query(":MEAS:STAT?")
        
    @selected_measurement_statistic.setter
    def selected_measurement_statistic(self, value):
        self.send(":MEAS:STAT {0}".format(value))
    
    @Feat(values={True: 1, False: 0})
    def _include_measurement_result_code(self):
        """Enable measurement result codes with measurment queries when True.
        
        **NOTE:**
        This should really only be used by developers and hackers.
        """
        return int(self.query(":MEAS:SEND?"))
        
    @_include_measurement_result_code.setter
    def _include_measurement_result_code(self, value):
        self.send(":MEAS:SEND {0}".format(value))
    
    @Feat()
    def displayed_results(self):
        """
        """
        orig_include_rescode = self._include_measurement_result_code
        self._include_measurement_result_code = True  # we NEED the state code.
        
        results = self.query(":MEAS:RES?")
        results_list = results.split(',')
        # interpret the results based on the selected stats:
        meas_stat = self.selected_measurement_statistic
        retval = None  # this will be filled in by decision block...
        if meas_stat != 'all':
            # all of the even elements are the stats,
            # and the odd elements are the result codes
            # Because there are NO names included, we can truly only
            # construct a list of dicts, and return it:
            results_labels = [meas_stat, 'validity state']
            list_of_dicts = []
            for i in range(0, len(results_list), 2):
                list_of_dicts.append( 
                    {k:v for (k,v) in zip(results_labels, results_list[i:i+2])} )
            retval = list_of_dicts
        else:
            # the measurement results are returned in the form:
            # <label>, <current>, <state>, <min>, <max>, <mean>,
            #   <stddev>, <#ofmeas>, ... (for UP TO 5 continous measurements)
            # In this case, we return a dict of dicts:
            results_labels = ['current', 'validity state', 'minimum', 
                              'maximum', 'mean', 'standard deviation', 
                              'measurement count']
            dict_of_dicts = {}
            for i in range(0, len(results_list), 8):
                dict_of_dicts[results_list[i]] = ( 
                    {k:v for (k,v) in zip(results_labels, results_list[i+1:i+8])} )
            retval = dict_of_dicts
        # end if
        self._include_measurement_result_code = orig_include_rescode
        
        # We have a nice class for the measurement results, let's use it:
        #MeasurementResult(label=)
        return retval
    
    @Action()
    def get_system_setup_binary(self):        
        self.send(":SYST:SET?")
        return read_definite_length_block(self.raw_recv, block_id={
                    'name': 'setup', 'model': 'Infiniium 90000 Series'},
                    recv_termination=self.RECV_TERMINATION, 
                    recv_chunk=self.RECV_CHUNK)


class DSOX92504A_TCP(Infiniium90000, ErrorQueueImplementation, 
                 ErrorQueueInstrument, IEEE4882SubsetMixin,
                 IORateLimiterMixin, TCPDriver):
    """Agilent Infiniium DSAX92504A Oscilloscope TCP Socket Driver
    """    
    #: Encoding to transform string to bytes and back as defined in
    #: http://docs.python.org/py3k/library/codecs.html#standard-encodings
    ENCODING = 'latin1'  # some funky characters this way come.

