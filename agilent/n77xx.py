# -*- coding: utf-8 -*-
"""
    sindri.agilent.n77xx
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control an Agilent N77XX Series Optical Devices

    N77XX Series::
    
        - N7744A and N7745A Optical Multiport Power Meters
        - N7751A and N7752A Variable Optical Attenuators, 2-Channel Power Meter
        - N7761A, N7762A, and N7764A Variable Optical Attenuators
        - N7766A and N7768A variable Optical Multimode Attenuators
        - N7711A and N7714A Tunable Laser System Source
        - N773xA Optical Switch
        
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
        - Agilent N77XX Series Programming Guide (P/N: N77XX-90C01, Sept. 2011)

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""
import struct
from lantz import Feat, DictFeat, Q_, Action
from sindri.mixins import IORateLimiterMixin, ErrorQueueInstrument
from lantz.network import TCPDriver
from lantz.visa import USBVisaDriver
from lantz.errors import InstrumentError
from sindri.errors import (PresetHasUnsavedChangesError, PresetError,
                           UndefinedError, UndefinedStorageLocationError,
                           InvalidPresetError, ProtectedPresetError)
from sindri.ieee4882.arbitrary_block import read_definite_length_block
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


#==============================================================================
# See pp.28-35 of the N77XX Programming Guide for information about how the
# commands are divided among the different classes of device in the series.
# The section is titled, ``Specific Command Summary``.
#==============================================================================
class N77XX(object):
    """Agilent N77XX Series Universal Features
    """
    __TRIGGER_CONFIGS = {'disabled': 'DIS', 'default': 'DEF', 
                         'passthrough': 'PASS', 'loopback': 'LOOP'}
    
    __CHANNEL_MAP = None
        
    @property
    def _channel_map(self):
        """The logical channel id to physical channel number (instrument-side) mapping.
        
        :type: dict
        
        This can be useful for mapping a continuous range of numbers 
        (e.g., 0-9) to a disjoint range of channel numbers on the instrument
        (e.g., 1-2, 3-4, 5-6, etc.). This may be the case when instrument
        inputs and outputs are enumerated separately, but are, in fact, linked
        with regard to command functions. Furthermore, this can be used to 
        give ``human-friendly`` names to the channels instead of numbers.
        
        **NOTE:**
        If this map is not None, then the channel keys (identifiers) will be
        limited to those keys contained in the dictionary!        
        
        This mapping will affect all features which utilize channel id
        specification.
        """
        return self.__CHANNEL_MAP
    
    def _map_channel_key(self, key):
        channel = key
        if self._channel_map:
            if key not in self._channel_map:
                raise KeyError("'{0}' is not a valid channel key".format(key))
            else:
                channel = self._channel_map[key]
        return channel    
    
#    def __init__(self, *args, **kwargs):
#        super().__init__(*args, **kwargs)    
    
    def _validate_preset_location(self, location):
        """Validate the given preset location index.
        
        :raises: UndefinedStorageLocationError
        :raises: InvalidPresetError
        """
        if location is None:
            try:
                location = self.preset
            except PresetError:
                raise UndefinedStorageLocationError()
        elif not (0 <= location <= self.preset_count):
            raise InvalidPresetError()
    
    @Action()
    def recall_state(self, location=None):
        """This command recalls a previously stored state. 
        
        Recall a setting from FLASH memory.        
        
        To recall a stored state, you must use the same memory location used 
        previously to store the state.
        
        :param location: The storage space index in which to store.
            - The default storage location is the currently selected preset.
            - If no preset is currently selected, and no location is given, an 
              error is raised.
              
        **NOTE:** Preset index ``0`` is reserved for the default settings
        configuration for the instrument! You cannot overwrite (save) to that
        preset.
              
        :raises: UndefinedStorageLocationError
        :raises: InvalidPresetError
        
        **NOTE**: This is NOT the IEEE488.2 command, but is equivalent.
        """
        self._validate_preset_location(location)
        if location == 0:
            # this is the reserved preset for the default configuration!
            self.send(":CONF:MEAS:SETT:PRES")
            self.refresh('preset')  # sync. the ``preset`` feature w/ actual
        else:
            self.send(":CONF:MEAS:SETT:REC {}".format(location))
            # force preset # to synchronize on instrument!
            # if not saved to location, then the instrument marks preset as
            # ``-1`` to indicate that current preset has ``unsaved`` changes.
            self.save(location)
    
    @Action()
    def save_state(self, location=None):
        """This command stores the present state of the power supply. 
        
        To recall a stored state, you must use the same memory location used 
        previously to store the state.
        
        :param location: The storage space index in which to store.
            - The default storage location is the currently selected preset.
            - If no preset is currently selected, and no location is given, an 
              error is raised.
              
        **NOTE:** Preset index ``0`` is reserved for the default settings
        configuration for the instrument! You cannot overwrite (save) to that
        preset.
              
        :raises: UndefinedStorageLocationError
        :raises: InvalidPresetError
        :raises: ProtectedPresetError
        
        **NOTE**: This is NOT the IEEE488.2 command, but is equivalent.
        """
        self._validate_preset_location(location)
        if location == 0:
            # this is the reserved preset for the default configuration!
            raise ProtectedPresetError("Cannot overwrite default configuration!")
        
        self.send(":CONF:MEAS:SETT:SAVE {}".format(location))
        self.refresh('preset')    
    
    #==========================================================================
    # ``SYSTem`` subsystem
    #
    # The SYSTem subsystem lets you control the instrument’s
    # serial interface. You can also control some internal data (like
    # date, time, and so on).
    #==========================================================================    
    @Feat(read_once=True)
    def headers(self):
        """A list of ALL of the SCPI command headers.
        """
        self.query(":SYST:HELP:HEAD?")
        
    @Action()
    def reboot(self):
        """Reboots the instrument.
        """
        self.send(":SYST:REB")
        
    @Feat(read_once=True)
    def scpi_version(self):
        """Returns the SCPI revision to which the instrument complies.

        :returns: SCPI version.
        :type: str
        
        The returned value is of a string in the form YYYY.V where the “Y’s” 
        represent the year of the version, and the “V” represents a version 
        number for that year (for example, 1995.0).
        """
        return self.query(':SYST:VERS?')
        
    @Action()
    def start_flashing_lan_led(self):
        """Instruct the LAN LED on the instrument to continually flash.
        
        This can be useful for identifying the specific instrument in a busy
        environment.
        """
        self.send("SYST:LXI:IDN ON")
        
    @Action()
    def stop_flashing_lan_led(self):
        """Instruct the LAN LED on the instrument to return to normal function.
        
        The LAN LED will show the current LAN state instead of flashing.        
        
        The flashing state can be useful for identifying the specific 
        instrument in a busy environment.
        """
        self.send("SYST:LXI:IDN OFF")
    
    #==========================================================================
    # ``SYSTem:COMMunicate`` subtree
    #==========================================================================
    _GETP_SETP_GPIB_ADDRESS = (None, int)
    @Feat(procs=(_GETP_SETP_GPIB_ADDRESS, ), limits=(0, 30, 1))
    def gpib_address(self):
        """The gpib address of the instrument (0-30, 21 is often reserved).
        
        :type: int
        """
        return int(self.query(":SYST:COMM:GPIB:SELF:ADDR?"))
    
    @gpib_address.setter
    def gpib_address(self, value):
        self.send(":SYST:COMM:GPIB:SELF:ADDR {0}".format(value))

    @Feat()
    def mac_address(self):
        """The mac address of the instrument.
        
        The Media Access Control (MAC) number is a unique number associated 
        with each instrument's network adapter.
        
        :type: str
        """
        return self.query(":SYST:COMM:ETH:MAC?")
        
    @Feat(values={True: 1, False: 0})
    def dhcp_enabled(self):
        """Enables use of DHCP for LAN communication interface.
        
        If DHCP/AutoIP is enabled, the optical power meter may use
        other parameters than specified explicitly, that is, it will use
        the parameters provided by the DHCP server. It tries to use
        its configured hostname (which may fail, depending on the
        network setup).
        """
        return int(self.query(":SYST:COMM:ETH:DHCP:ENAB?"))
        
    @dhcp_enabled.setter
    def dhcp_enabled(self, value):
        self.send(":SYST:COMM:ETH:DHCP:ENAB {0}".format(value))
        
    @Feat(values={True: 1, False: 0})
    def auto_ip_enabled(self):
        """Enables use of AutoIP for LAN communication interface.
        
        N7744A and N7745A require FW Version 1.16 or higher.
        
        Enable or disable whether IP addresses can be created automatically 
        by the instrument. Automatic IP addressing is only used if DHCP is 
        enabled, but the instrument cannot find a DHCP server.        
        
        If DHCP/AutoIP is enabled, the optical power meter may use
        other parameters than specified explicitly, that is, it will use
        the parameters provided by the DHCP server. It tries to use
        its configured hostname (which may fail, depending on the
        network setup).
        """
        return int(self.query(":SYST:COMM:ETH:AUTO:ENAB?"))
        
    @auto_ip_enabled.setter
    def auto_ip_enabled(self, value):
        self.send(":SYST:COMM:ETH:AUTO:ENAB {0}".format(value))
        
    @Action()
    def save_network_settings(self):
        """Save the system’s network interface parameters.
        """
        self.send(":SYST:COMM:ETH:SAVE")
        
    @Action()
    def revert_network_settings(self):
        """Undo all changes to the network parameters that have been made.
        
        The changes must have been made after the last save, reboot or network
        interface restart command!
        """
        self.send(":SYST:COMM:ETH:CANC")
        
    @Action()
    def restart_network_interface(self):
        """Restarts the network interface for the instrument with the new parameters.
        
        This command only works if the instrument has a working network 
        connection at the time the command is issued. If you are connected by 
        USB, use ``save_network_settings`` followed by an instrument reboot.
        
        **NOTE:** In most cases, instead of using this restart command, it is 
        better to save the new parameters (``save_network_settings``) and
        reboot the instrument (``reboot``).
        """
        self.send(":SYST:COMM:ETH:REST")
        
    @Action()
    def reset_network_settings(self):
        """Resets all the LAN parameters to the factory default.
        
        The factory defaults are:
            - DHCP On
            - AutoIP On
            - Hostname is a concatenation of product number and serial number.
            - The password for the web based LAN configuration interface is 
            reset to ‘agilent’.

        This command is also triggered when the reset button on the front panel 
        is pressed longer than 3 seconds.
        """
        self.send(":SYST:COMM:ETH:CANC")
    
    @Feat()
    def ip_address(self):
        """The current network ip address of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:IPAD:CURR?").strip('"')
        
    @Feat()
    def subnet_mask(self):
        """The current network subnet mask setting of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:SMASK:CURR?").strip('"')
    
    @Feat()
    def default_gateway(self):
        """The current network default gateway setting of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:DGAT:CURR?").strip('"')
    
    @Feat()
    def host_name(self):
        """The current network host name of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:HOST:CURR?").strip('"')
        
    @Feat()
    def domain_name(self):
        """The current network domain name of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:DOM:CURR?").strip('"') 
    
    @Feat()
    def netconfig_ip_address(self):
        """The manual network configuration ip address of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        
        If you query one of the alterable parameters, you always get the most 
        recently set value, even if you have not yet activated it.

        To undo any changes before they become active, revert the network 
        settings using ``revert_network_settings``.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:IPAD?").strip('"')
        
    @netconfig_ip_address.setter
    def netconfig_ip_address(self, value):
        self.send(":SYST:COMM:ETH:IPAD \"{0}\"".format(value))
        
    @Feat()
    def netconfig_subnet_mask(self):
        """The current network subnet mask setting of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        
        If you query one of the alterable parameters, you always get the most 
        recently set value, even if you have not yet activated it.

        To undo any changes before they become active, revert the network 
        settings using ``revert_network_settings``.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:SMASK?").strip('"')
        
    @netconfig_subnet_mask.setter
    def netconfig_subnet_mask(self, value):
        self.send(":SYST:COMM:ETH:SMASK \"{0}\"".format(value))
    
    @Feat()
    def netconfig_default_gateway(self):
        """The current network default gateway setting of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        
        If you query one of the alterable parameters, you always get the most 
        recently set value, even if you have not yet activated it.

        To undo any changes before they become active, revert the network 
        settings using ``revert_network_settings``.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:DGAT?").strip('"')
        
    @netconfig_default_gateway.setter
    def netconfig_default_gateway(self, value):
        self.send(":SYST:COMM:ETH:DGAT \"{0}\"".format(value))
    
    @Feat()
    def netconfig_host_name(self):
        """The current network host name of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        
        If you query one of the alterable parameters, you always get the most 
        recently set value, even if you have not yet activated it.

        To undo any changes before they become active, revert the network 
        settings using ``revert_network_settings``.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:HOST?").strip('"')
        
    @netconfig_host_name.setter
    def netconfig_host_name(self, value):
        self.send(":SYST:COMM:ETH:HOST \"{0}\"".format(value))
        
    @Feat()
    def netconfig_domain_name(self):
        """The current network domain name of the instrument.
        
        :type: str
        
        You must reboot the instrument or restart the network interface before 
        any alterations to the ethernet parameters become effective.
        
        If you query one of the alterable parameters, you always get the most 
        recently set value, even if you have not yet activated it.

        To undo any changes before they become active, revert the network 
        settings using ``revert_network_settings``.
        """
        # the field value string comes back with enclosing quotes;
        # therefore, we strip the '"' char.
        return self.query(":SYST:COMM:ETH:DOM?").strip('"')
        
    @netconfig_domain_name.setter
    def netconfig_domain_name(self, value):
        self.send(":SYST:COMM:ETH:DOM \"{0}\"".format(value))
    
    #==========================================================================
    # ``CONFigure:MEASurement:SETTing`` subtree
    #==========================================================================
    @Feat(read_once=True)
    def preset_count(self):
        """The number of preset storage spaces.
        
        In addition to the settings spaces in FLASH memory, the working 
        memory can hold a setting.
        """
        return int(self.query(":CONF:MEAS:SETT:NUMB?"))
    
    @Action()
    def get_current_preset(self):
        """Get the index of the setting currently being used.
        
        :returns: The index of the setting currently being used.
        :type int:
        
        A value > 0 is returned if the setting has been stored in FLASH memory, 
        or has been recalled from FLASH memory, and has not been changed since.

        0 is returned if the setting has not yet been stored.
        
        0 is returned if the FLASH setting has been deleted since the last 
        recall or save.
        
        -1 is returned if the setting was changed but has not been saved yet.
        """
        return int(self.query(":CONF:MEAS:SETT:ACT?"))
        
    @Feat()
    def preset(self):
        """The currently selected measurement configuration preset.
        
        **NOTE:** Preset index ``0`` is reserved for the default settings
        configuration for the instrument! You cannot overwrite (save) to that
        preset.
        
        The instrument can store a number of settings in FLASH memory. 
        The number of memory places can be queried with ``preset_count``.
        
        For the Multiport Power Meters, a measurement setting consists of all 
        parameters which can be set with the :SENSe:* commands.
        
        For the variable optical attenuators, a measurement setting consists 
        of all parameters of the following commands:
            - INPut:CHANnel:ATTenuation
            - INPut:CHANnel:ATTenuation:SPEed
            - INPut:CHANnel:OFFSet
            - INPut:CHANnel:WAVelength
            - OUTput:CHANnel:ATIMe
            - OUTput:CHANnel:POWer:OFFSet
            - OUTPut:CHANnel:POWer:UNit
            - OUTPut:CHANnel:POWer:CONTRol
            - OUTPut:CHANnel:POWer
            - OUTPut:CHANnel[:STATe]
            - OUTPut:CHANnel[:STATe]:APOWeron
            - The table of wavelength dependent offsets is automatically 
            stored in the non- volatile RAM when the offset table state has 
            been set to ON. (That is, :CONFigure:OFFSet:WAVelength:STATe 1)
            
        After a preset change, you can dequeue and error to check if it is OK.
        
        :raises: InvalidPresetError
        :raises: ProtectedPresetError
        """
        current_preset = self.get_current_preset()
        if current_preset == -1:
            raise PresetHasUnsavedChangesError()
        elif current_preset == 0:
            return None
        elif current_preset < -1:
            raise UndefinedError()
        #else:
        return current_preset
        
    @preset.setter
    def preset(self, value):
        self.recall_state(value)
        
    @Action()
    def revert_state(self):
        """Discard all the changes to the setting after the last save or recall.
        """
        self.send(":CONF:MEAS:SETT:CANC")
    
    @Action()
    def reset_presets(self):
        """Sets the insrument to its standard settings, and erases presets. 
        
        NOTE: ALL stored settings presets are deleted.
        
        By contrast, recalling preset ``0`` keeps the previously stored 
        settings in nonvolatile RAM and they can be recalled again, while 
        restoring the current settings to the default configuration.

        In contrast with the full ``reset``, the following are NOT affected by 
        this command:
            - The GPIB, USB and LAN (interface) state,
            - The interface addresses,
            - The output and error queues,
            - The Service Request Enable register (SRE)
            - The Status Byte (STB)
            - The Standard Event Status Enable Mask (SESEM)
            - The Standard Event Status Register (SESR).
        """
        self.send(":SYST:PRES")
    
    @Action()
    def erase_preset(self, preset):
        """Erase a setting from memory.
        
        :param preset: The index of the preset to erase.
        :type int:
        """
        self.send(":CONF:MEAS:SETT:ERAS")
    
    @Action()
    def _get_all_units(self):
        """Get the power unit for all ports of the instrument, as a list.
        
        There is not header information in the data, the unit indicators
        are simply ordered according to port number.
        
        **NOTE:**
        This should generally NOT be used by anyone, except for developers
        and hackers.
        """
        response = self.query(":SENS:POW:UNIT:ALL:CSV?")
        units_string = response.replace('0', 'dBm')  # decibel milliwatt
        units_string = units_string.replace('1', 'W')  # watt
        units_list = units_string.split(',')[:-1]  # create list, no null terminator
        units_dict = {i:u for (i,u) in enumerate(units_list, 1)}
        return units_dict
        
    @Action()
    def _set_power_units(self, port_num, unit_string):
        """Set the power unit for a given port of the instrument.
        
        The unit string values can be one of the following:
            - ``dbm`` := decibel milliwatt (dBm)
            - ``watt`` := Watt (W)
            - Any other magical value that you are aware of, which works. :)
            
        The unit string is NOT case sensitive. The set of accepted unit strings
        is NOT strict, and is NOT checked before sending to the instrument.
        
        **NOTE:**
        This should generally NOT be used by anyone, except for developers
        and hackers.
        """
        self.send(":OUTP{0}:POW:UN {1}".format(port_num, unit_string.upper()))
    
    #==========================================================================
    # ``:TRIGger`` subtree
    #==========================================================================
    @property
    def trigger_configurations(self):
        """A list of available trigger configurations.
        
        - ``disabled``: Trigger connectors are disabled.
        
        - ``default``: The ``Input Trigger Connector`` is activated, the 
        incoming trigger response for each slot/port determines how each slot 
        responds to an incoming trigger, all slot/port events can trigger the 
        ``Output Trigger Connector``.
        
        - ``passthrough``: The same as DEFault but a trigger at the 
        ``Input Trigger Connector`` generates a trigger at the 
        ``Output Trigger Connector`` automatically.
        
        - ``loopback``: The same as ``passthrough`` (compatibility reasons).
        """
        return list(self.__TRIGGER_CONFIGS.keys())
    
    @Feat(values=__TRIGGER_CONFIGS)
    def trigger_configuration(self):
        """The hardware trigger configuration with regard to ``Trigger Connectors``
        
        .. seealso: ``trigger_configurations``
        """
        return self.query(":TRIG:CONF?")
        
    @trigger_configuration.setter
    def trigger_configuration(self, value):
        self.send(":TRIG:CONF {0}".format(value))


class Attenuator(object):
    """Agilent N77XX Series Attenuator Features
    
    This class depends on some features/properties which are present in the
    ``N77XX`` class. The intention is that this class will be mixed-in with
    that class in the inheritance chain. The following features/properties
    are those aforementioned:
    
        - method: ``_map_channel_key``
    """
    #==========================================================================
    # ``:CONFigure:OFFSet:WAVelength`` subtree
    #==========================================================================
    @DictFeat(values={True: 1, False: 0})
    def wavelength_offset_enabled(self, key):
        """Wavelength-dependent power offset enabled state.
        
        Specifies whether the attenuator uses its λ offset table to compensate 
        for wavelength dependent losses in the the test set-up. This table 
        contains the additional power offset to be applied, for each 
        wavelength specified.
        
        This command does not affect the instrument’s internal enviromental 
        temperature and optical wavelength compensation, which remain active.
        
        There is only one λ offset table available for all attenuator channels.
        
        .. seealso: ``wavelength_offset``
        """
        channel = self._map_channel_key(key)
        
        return int(self.query(":CONF{0}:OFFS:WAV:STAT?".format(channel)))
        
    @wavelength_offset_enabled.setter
    def wavelength_offset_enabled(self, key, value):
        channel = self._map_channel_key(key)
                
        self.send(":CONF{0}:OFFS:WAV:STAT {1}".format(channel, value))
        
    @DictFeat()
    def wavelength_offset_reference(self, key):
        """The reference power meter against which offsets MAY be computed.
        
        Specifies the slot and channel of the external powermeter used when
        setting a wavelength-offset table entry ``relative to reference``.
        
        Example:
            >>> inst.wavelength_offset_reference[1] = {'slot': 0, 'channel': 1}
        
        **NOTE:**
        This value MUST be a dictionary containing entries for the keys: 
        ``slot`` and ``channel``. These entries correspond to the slot and
        channel numbers for the target powermeter to be used as the reference.
        
        **NOTE:**
        The slot and channel numbers for this feature correspond to the 
        PHYSICAL slot and channel numbers on the device, NOT the logical
        numbers used within the driver!
        
        :raises: KeyError
        
        .. seealso: ``wavelength_offset``
        """
        channel = self._map_channel_key(key)
        
        resp = self.parse_query(":CONF{0}:OFFS:WAV:REF?".format(channel),
                                format='{slot:s},{channel:s}')
        # no cheap tricks needed:
        return {'slot': int(resp['slot']), 'channel': int(resp['channel'])}
                                
    @wavelength_offset_reference.setter
    def wavelength_offset_reference(self, value, key):
        channel = self._map_channel_key(key)
                
        self.send(":CONF{0}:OFFS:WAV:REF {1},{2}".format(channel, 
                  value['slot'], value['channel']))
                  
    @Action()
    def clear_wavelength_offset_table(self, channel_key):
        """Clear the wavelength vs. power offset table for a given channel.
        
        Deletes every value pair (wavelength:offset) from the offset table!
        """
        channel = self._map_channel_key(channel_key)
        
        self.send(":CONF{0}:OFFS:WAV:VAL:DEL:ALL".format(channel))
    
    @Action(units=('', 'nm', 'dB', ''))
    def set_wavelength_offset_entry(self, channel_key, wavelength, 
                                    offset=Q_(0, 'nm'), to_ref=False):
        """Write/override a given wavelength-offset value in channel's table.
        
        If the ``to_ref`` keyword evaluates to ``True``, then the instrument 
        calculates the difference between the power measured by an external
        powermeter and the power measured by the attenuator’s integrated
        powermeter, and stores it as the offset. The equation is as follows:

        P Offset ( λ )(dB) = P att (dBm) - P ext (dBm)
        """
        channel = self._map_channel_key(channel_key)
        
        self.send(":CONF{chn}:OFFS:WAV:VAL {lmbd} NM, {offs}".format(
            chn=channel, lmbd=wavelength, 
            offs=(offset if not to_ref else 'TOREF') ))
        
    @Action()
    def get_wavelength_offset_table_binary(self, channel_key):
        """Retrieve the binary block of data for the wavelength-offset table.
        
        Binary block format format (Intel byte order); wavelength:offset pairs 
        in ascending order. Each value pair is transferred as 12 bytes; 8 bytes
        represent the wavelength, 4 bytes represent the offset. 
        
        :returns: Definite/Indefinite Length Arbitrary Block Binary Data
        :type sindri.ieee4882.arbitrary_block.ArbitraryBlock:
        
        .. seealso: sindri.ieee4882.arbitrary_block.DefiniteLengthBlock
        .. seealso: sindri.ieee4882.arbitrary_block.IndefiniteLengthBlock
        """
        channel = self._map_channel_key(channel_key)
        
        self.send(":CONF{0}:OFFS:WAV:TAB?".format(channel))
        return read_definite_length_block(self.raw_recv, block_id={
                    'name': 'wavelength-offset table', 'channel': channel},
                    recv_termination=self.RECV_TERMINATION, 
                    recv_chunk=self.RECV_CHUNK)
                    
    @Action()
    def get_wavelength_offset_table(self, channel_key):
        """Retrieve the wavelength-offset table from the instrument.
        
        :param: channel_key
        :type int:
        
        :returns: wavelength-offset table
        :type dict:
        
        .. seealso: get_wavelength_offset_table_binary
        """
        tbl_binary = self.get_wavelength_offset_table_binary(channel_key)
        # the table is organized as twelve byte chunks,
        # one twelve byte chunk per entry:
        data_length = len(tbl_binary.data)
        entries = [tbl_binary.data[i:i+12] for i in range(0, data_length, 12)]
        # each entry is composed of an 8 byte double precision wavelength,
        # and a 4 byte single precision offset value:
        table = {}
        for entry in entries:
            wavelength = struct.unpack('<d', entry[:8])[0]
            offset = struct.unpack('<f', entry[8:])[0]
            table[wavelength] = offset
        return table
    
    @DictFeat(read_once=True)
    def max_wavelength_offset_entries(self, key):
        """The maximum # of entries (wavelength-offset pairs) possible for a given channel.
        
        .. seealso: set_wavelength_offset
        """
        channel = self._map_channel_key(key)
        return self.query(":CONF{0}:OFFS:WAV:TAB:SIZE? MAX".format(channel))
        
    @DictFeat(read_once=True)
    def min_wavelength_offset_entries(self, key):
        """The minimum # of entries (wavelength-offset pairs) possible for a given channel.
        
        .. seealso: set_wavelength_offset
        """
        channel = self._map_channel_key(key)
        return self.query(":CONF{0}:OFFS:WAV:TAB:SIZE? MIN".format(channel))
        
    @DictFeat()
    def wavelength_offset_entries_count(self, key):
        """The current # of entries (wavelength-offset pairs) for a given channel.
        
        .. seealso: set_wavelength_offset
        """
        channel = self._map_channel_key(key)
        return self.query(":CONF{0}:OFFS:WAV:TAB:SIZE?".format(channel))

    #==========================================================================
    # ``:INPut`` subtree
    #==========================================================================
    @DictFeat(units='decibel')
    def attenuation(self, key):
        """The attenuation factor (α) for a given channel (unit := decibel)
        
        Sets the attenuation factor (α) for the slot. The attenuation factor 
        is used, together with an offset factor (α Offset) to set the filter 
        attenuation (α filter). 
        
        α_new (dB) = α (dB) + α_offset (dB)
        """
        channel = self._map_channel_key(key)
        return self.query(":INP{0}:ATT?".format(channel))
        
    @attenuation.setter
    def attenuation(self, key, value):
        channel = self._map_channel_key(key)
        self.send(":INP{0}:ATT {1}".format(channel, value))
        
    @Action(units='decibel')
    def set_all_attenuation(self, value):
        """Set the attenuation factor for ALL channels to the given value (units := decibel)
        
        If any of the attenuators do not support the attenuation factor, an 
        error is pushed to the error queue (-224, illegal parameter value).
        """
        self.send(":INP:ATT:ALL {0}".format(value))
        
    @DictFeat(units='decibel')
    def offset(self, key):
        """The offset factor (α Offset ) for the given channel. (units := decibel)
        
         This factor does not affect the filter attenuation (α filter). It is 
         used to offset the attenuation factor values. This offset factor is 
         used, with the attenuation factor, to set the attenuation of the 
         filter. In this way it is possible to compensate for external losses.
        """
        channel = self._map_channel_key(key)
        return self.query(":INP{0}:OFFS?".format(channel))
        
    @offset.setter
    def offset(self, key, value):
        channel = self._map_channel_key(key)
        self.send(":INP{0}:OFFS {1}".format(channel, value))
     
    @DictFeat(units='decibel', read_once=True)
    def min_offset(self, key):
        """The minimum possible offset value for a given channel. (units := decibel)
        """
        channel = self._map_channel_key(key)
        return self.query(":INP{0}:OFFS? MIN".format(channel))     
     
    @DictFeat(units='decibel', read_once=True)
    def max_offset(self, key):
        """The maximum possible offset value for a given channel. (units := decibel)
        """
        channel = self._map_channel_key(key)
        return self.query(":INP{0}:OFFS? MAX".format(channel))
    
    # pay attention here... this matters.
    _GET_TRANS_SPEED_PROC = None
    _SET_TRANS_SPEED_PROC = lambda x: x if (0.1 <= x <= 80) else 'MAX' if (0.1 <= x) else 'MIN'
    _GETP_SETP_TRANS_SPEED = (_GET_TRANS_SPEED_PROC, _SET_TRANS_SPEED_PROC)
    
    @DictFeat(units='decibel/s', procs=(_GETP_SETP_TRANS_SPEED,))
    def transition_speed(self, key):
        """The attenuation transition speed for a given channel. (units := decibel/s)
        
        This is the speed at which the slot moves from one attenuation to
        another (in dB/s).
        """
        channel = self._map_channel_key(key)
        return self.query(":INP{0}:ATT:SPE?".format(channel))
        
    @transition_speed.setter
    def transition_speed(self, key, value):
        channel = self._map_channel_key(key)
        self.send(":INP{0}:ATT:SPE {1}".format(channel, value))
        if value in ['MIN', 'MAX']:
            self.log_warning("transition_speed actually set to {0}".format(value))
    
    @DictFeat(units='nm')
    def wavelength(self, key):
        """The attenuator channel's operating wavelength.(units := nm)
        
        This value is used to compensate for the wavelength dependence of the 
        filter, and to calculate a wavelegth dependent offset from the user 
        offset table (if enabled).
        """
        channel = self._map_channel_key(key)
        return float(self.query(":INP{0}:WAV?".format(channel))) * 1.0E+9 #nm
        
    @wavelength.setter
    def wavelength(self, key, value):
        channel = self._map_channel_key(key)
        self.send(":INP{0}:WAV {1} NM".format(channel, value))
        
    @DictFeat(units='nm', read_once=True)
    def max_wavelength(self, key):
        """The maximum operating wavelength for a given channel
        """
        channel = self._map_channel_key(key)
        return float(self.query(":INP{0}:WAV? MAX".format(channel))) * 1.0E+9 #nm
        
    @DictFeat(units='nm', read_once=True)
    def min_wavelength(self, key):
        """The minimum operating wavelength for a given channel
        """
        channel = self._map_channel_key(key)
        return float(self.query(":INP{0}:WAV? MIN".format(channel))) * 1.0E+9 #nm
        
    @Action(units='nm')
    def set_all_wavelength(self, value):
        """Sets the attenuator’s operating wavelength for all attenuators. (units := nm)
        """
        self.send("INP:WAV:ALL {0}".format(value))
        
    #==========================================================================
    # ``:OUTPut`` subtree
    #==========================================================================
    @DictFeat(values={True: 1, False: 0})
    def shutter_opened(self, key):
        """The state of the output shutter (opened/closed) for the given channel.
        
        This is essentially an output enable.
        
        **NOTE:** 
        The Shutter is closed at maximum speed, and opened at the configurated 
        attenuation speed.
        """
        channel = self._map_channel_key(key)
        return int(self.query(":OUTP{0}:STAT?".format(channel)))
        
    @shutter_opened.setter
    def shutter_opened(self, key, value):
        channel = self._map_channel_key(key)
        self.send(":OUTP{0}:STAT {1}".format(channel, value))


class MPPM_Attenuator(object):
    """Agilent N77XX Series Multi-Port Power Meter & Attenuator Common Features
    
    Multiport power meters are in the sub-series: ``N774xA``
    Attenuators are in the sub-series: ``N775xA`` AND ``N776xA``
    
    This class depends on some features/properties which are present in the
    ``N77XX`` class. The intention is that this class will be mixed-in with
    that class in the inheritance chain. The following features/properties
    are those aforementioned:
    
        - method: ``_map_channel_key``
    """
    #==========================================================================
    # ``:READ`` subtree
    #==========================================================================
    #@DictFeat(units='')
    pass


class PM_Attenuator(object):
    """Agilent N77XX Series Power Meter & Attenuator Common Features
    
    Multiport power meters are in the sub-series: ``N774xA`` AND ``N775xA``
    Attenuators are in the sub-series: ``N775xA`` AND ``N776xA``
    
    This class depends on some features/properties which are present in the
    ``N77XX`` class. The intention is that this class will be mixed-in with
    that class in the inheritance chain. The following features/properties
    are those aforementioned:
    
        - method: ``_map_channel_key``
    """
    pass


class ATTPM_Attenuator(object):
    """Agilent N77XX Series Atten. Power Meter Combo & Attenuator Common Features
    
    Attenuator power meter combos are in the sub-series: ``N775xA``
    Attenuators are in the sub-series: ``N775xA`` AND ``N776xA``
    
    This class depends on some features/properties which are present in the
    ``N77XX`` class. The intention is that this class will be mixed-in with
    that class in the inheritance chain. The following features/properties
    are those aforementioned:
    
        - method: ``_map_channel_key``
    """
    pass


class N77XX_TCP(N77XX, ErrorQueueImplementation, 
                ErrorQueueInstrument, IEEE4882SubsetMixin, 
                IORateLimiterMixin, TCPDriver):
    pass


class N77XX_USBVisa(N77XX, ErrorQueueImplementation, 
                    ErrorQueueInstrument, IEEE4882SubsetMixin, 
                    IORateLimiterMixin, USBVisaDriver):
    """This should use the VisaDriver to auto detect interface type... but...
    
    The VisaDriver auto-detect feature has some issues right now.
    """
    pass


class N7766A_TCP(Attenuator, MPPM_Attenuator, PM_Attenuator, ATTPM_Attenuator, 
                 N77XX, ErrorQueueImplementation, 
                 ErrorQueueInstrument, IEEE4882SubsetMixin,
                 IORateLimiterMixin, TCPDriver):
    """Agilent N7766A Optical Attenuator
    """
    _channel_map = {1: 1, 2: 3}
    
    #: Encoding to transform string to bytes and back as defined in
    #: http://docs.python.org/py3k/library/codecs.html#standard-encodings
    ENCODING = 'latin1'  # some funky characters this way come.

