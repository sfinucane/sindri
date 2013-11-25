# -*- coding: utf-8 -*-
"""
    sindri.anritsu.mx180000a
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers for the Anritsu MX180000A Control Interface

    Sources::

        - Anritsu Corporation `link <http://www.anritsu.com>`_

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""

__version__ = '0.1.0'

from lantz import Feat, DictFeat, Q_, Action
from lantz.errors import InstrumentError


class IEEE4882SubsetMixin(object):
    """IEEE 488.2 Command subset
    """
    @Feat(read_once=True)
    def idn(self):
        """Instrument identification.
        """
        idn_ = self.parse_query('*IDN?', 
                        format='{manufacturer:s},{model:s},{serialno:s}')
        # fill in the missing software version (MP1800A does not include):
        idn_['softno'] = None
        return idn_
    
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
        self.query("*ESE {0:d}".format(value))

    @Action()
    def clear_status(self):
        """Clears the event registers in all register groups.
         Also clears the error queue.
        """
        self.send('*CLS')
    
    # TODO: This does NOT neccessarily WAIT, might simply return ``0`` when not done!
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
        

class MX180000A(object):
    """Anritsu MX180000A SQA Controller Driver Kernel
    """
    __COMMON_FUNCTIONS = {'auto search': 'ASE', 
                          'isi': 'ISI',
                          'eye margin': 'EMAR',
                          'eye diagram': 'EDI',
                          'q': 'QAN',
                          'bathtub': 'BTUB',
                          'auto adjust': 'AADJ',
                          'off': 'OFF'}
    #==========================================================================
    # System level commands
    #==========================================================================
    @Action()
    def factory_reset(self):
        """Initializes the internal setting data to the initial settings at factory shipment.
        """
        self.send(":SYST:MEM:INIT")
        
    @Action()
    def recall_state(self, filename):
        """This command recalls a saved state from a given file on the instrument.
        
        This performs a ``Quick Recall``, which restores ALL of the settings
        for ALL of the modules from the given file.
        
        The filename should be of the format: ``C:\Test\example``
        
        **NOTE:**
        The settings will not be read from the saved file if the file name is 
        changed.
        """
        self.send(":SYST:MMEM:QREC \"{0}\"".format(filename))
    
    @Action()
    def save_state(self, filename):
        """This command stores the present state in a given file on the instrument. 
        
        This performs a ``Quick Store``, which saves ALL of the settings
        for ALL of the modules currently in the instrument.
        
        The filename should be of the format: ``C:\Test\example``
        
        **NOTE:**
        The settings will not be read from the saved file if the file name is 
        changed.
        """
        # file comment is limited to 59 chars:
        comment = "sindri.anritsu.mx180000a, {0}".format(__version__)
        self.send(":SYST:MMEM:QST \"{0}\", \"{1}\"".format(filename, comment))
        
    @Feat()
    def selected_unit(self):
        """The index of the unit being operated.
        """
        return self.query(":UENT:ID?")
        
    @selected_unit.setter
    def selected_unit(self, value):
        self.send(":UENT:ID {0}".format(value))
        
    @Feat()
    def selected_module(self):
        """The index of the module (slot position) being operated.
        """
        return self.query(":MOD:ID?")
        
    @selected_module.setter
    def selected_module(self, value):
        self.send(":MOD:ID {0}".format(value))
        
    @Feat()
    def selected_port(self):
        """The index of the port (physical position # on module) being operated.
        """
        return self.query(":PORT:ID?")
        
    @selected_port.setter
    def selected_port(self, value):
        self.send(":PORT:ID {0}".format(value))
        
    @Action()
    def get_software_status(self):
        """Query the software status of the MP1800A/MT1810A.
        
        Returns A LOT of useful information about the installed modules/options.
        """
        return self.query(":SYST:COND?")
        
    @Feat(values=__COMMON_FUNCTIONS)
    def selected_function(self):
        """The common/automatic measurement function to be performed.
        
        This should be set to ``off`` when attempting to control a specific
        unit:module:port, otherwise all commands will be regarded as intended
        for the common measurement function. When set to ``off``, the 
        previously set unit:module:port will be the current setting.
        """
        return self.query(":SYST:CFUN?")
        
    @selected_function.setter
    def selected_function(self, value):
        self.send(":SYST:CFUN {0}".format(value))
    
    

