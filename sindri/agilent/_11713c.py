# -*- coding: utf-8 -*-
"""
    sindri.agilent.11713c
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control an Agilent 11713C Attenuator/Switch Driver
        
    N.B.:
    
        - Binary data is transmitted as big endian; that is, bytes must be 
          swapped for Intel platforms.
        - Blocks have the form: ``#nl...ld...d``. ``n`` is the number of digits 
          of ``l...l``. ``l...l`` gives the length of the data part ``d...d``. 
          For example, ``#212Hello world``, where ``#`` indicates a block, 
          ``2`` gives the 2 digit length, “12” indicates 12 bytes, and 
          ``Hello world`` is the 12 data bytes.
        - Agilent instruments have standardized on using port 5025 for SCPI 
          socket services. Once a connection is made you simply send the SCPI 
          strings to the instrument and read back responses over the socket 
          connection. All strings must be terminated with a newline character. 
          All responses from the instrument will be terminated with a newline 
          character. (Published: September, 2011)

    Sources::

        - Agilent Technologies `link <http://www.agilent.com>`_
        - Agilent 11713C Operating and Service Manual (P/N: 11713-90024, Jan. 2010)

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""
from lantz import Feat, DictFeat, Q_, Action
from sindri.mixins import IORateLimiterMixin, ErrorQueueInstrument
from lantz.network import TCPDriver
from lantz.errors import InstrumentError
from sindri.errors import UndefinedError
from .common import ErrorQueueImplementation

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
    
    @Feat(read_once=True)
    def fitted_options(self):
        """Fitted options.
        """
        return self.query('*OPT?').split(',')


class _11713C(object):
    """
    """
    @Action()
    def close_paths(self, *args):
        """Close (set HIGH) the specified switch paths.
        
        There are two available banks on the 11713C, but this action does NOT
        prevent you from trying others.
        
        :param: paths_list
        :type list:
        :description: A list of switch paths (bank+channel), per the instrument manual.
        """
        paths_list = self._generate_paths_list(*args)
        self.send(":ROUTE:CLOSE (@{0})".format(','.join(paths_list)))

    @Action()
    def open_paths(self, *args):
        """Open (set LOW/GND) the specified switch path
        
        There are two available banks on the 11713C, but this action does NOT
        prevent you from trying others.
        
        :param: paths_list
        :type list:
        :description: A list of switch paths (bank+channel), per the instrument manual.
        """
        paths_list = self._generate_paths_list(*args)
        self.send(":ROUTE:OPEN (@{0})".format(','.join(paths_list)))
        
    @Action()
    def get_states(self, *args):
        """Get the state of each specified switch path (opened|closed)
        
        There are two available banks on the 11713C, but this action does NOT
        prevent you from trying others.
        
        :param: paths_list
        :type list:
        :description: A list of switch paths (bank+channel), per the instrument manual.
        """
        paths_list = self._generate_paths_list(*args)
        response = self.query(":ROUTE:OPEN? (@{0})".format(','.join(paths_list)))
        response_list = response.split(',')
        state_map = {'0': 'closed', '1': 'opened'}
        states_list = [state_map[x] for x in response_list]
        return states_list
        
    @Action()
    def close_all_paths(self):
        """Close (set HIGH) ALL paths.
        """
        self.send(":ROUTE:CLOSE:ALL")
        
    @Action()
    def open_all_paths(self):
        """Open (set LOW/GND) ALL paths.
        """
        self.send(":ROUTE:OPEN:ALL")


class _11713C_TCP(_11713C, ErrorQueueImplementation, 
                 ErrorQueueInstrument, IEEE4882SubsetMixin,
                 IORateLimiterMixin, TCPDriver):
    """Agilent N7766A Optical Attenuator
    """
    _channel_map = {1: 1, 2: 3}
    
    #: Encoding to transform string to bytes and back as defined in
    #: http://docs.python.org/py3k/library/codecs.html#standard-encodings
    ENCODING = 'latin1'  # some funky characters this way come.

