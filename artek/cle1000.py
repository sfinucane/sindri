# -*- coding: utf-8 -*-
"""
    sindri.artek.cle1000
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control the Artek CLE1000 Variable ISI Channel

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
        return self.parse_query('*IDN?', 
                format='{manufacturer:s},{model:s},{serialno:s},{softno:s}')
    
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
  

class CLE1000(object):
    """Artek CLE1000 Variable ISI Channel Core Features
    
    **NOTE:**
    DO NOT begin SCPI messages/commands with the ``:``, EVER.
    
    1) Difference between Start‐up and *RST
        - When System Start‐up:
            - ISI Value: as the front panel dial specifies
        - When *RST executed:
            - ISI Value becomes 0
            
    2) No Trigger supported
    
    3) Multiple commands can be received up to 127 characters.
    """
    __OPER_STATUS_MESSAGES = {0: 'None.',
                              1: 'No ISI value specified.'}
    
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
    @Feat()
    def operation_status(self):
        """The operation status as determined by the Operation Status Register.
        
        Qeuries and interprets the Operation Status Register value.
        
        :returns: (status_code, status_message)
        :type (int, str):
        """
        status_code = int(self.query("STAT:OPER:COND?"))
        return (status_code, self.__OPER_STATUS_MESSAGES.get(status_code, ''))
        
    @Action()
    def clear_operation_status(self):
        """Clear the operation status (by clearing the Operation Status Register).
        """
        self.query("STAT:OPER?")
        
    @Feat(limits=(0, 100))
    def isi_value(self):
        """The ISI (loss) amount in percentage of CLE1000’s dynamic range (0.0% - 100.0%).
        """
        return float(self.query())
        
    @isi_value.setter
    def isi_value(self, value):
        self.send("OUTP:ISI {0}".format(value))
        
    
        

class CLE1000_Serial(CLE1000, ErrorQueueImplementation, 
                    ErrorQueueInstrument, IEEE4882SubsetMixin, 
                    IORateLimiterMixin, SerialDriver):
    ENCODING = 'ascii'

    RECV_TERMINATION = '\n'
    SEND_TERMINATION = '\n'
    
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


