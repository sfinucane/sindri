# -*- coding: utf-8 -*-
"""
    sindri.agilent.n490x
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control an Agilent N490x Series BERTs.
    
    Supported BERT Models:
    ======================
    
        - N4903B J-BERT
        
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
        - Agilent J-BERT N4903B Programming Guide (P/N: N4903-91031, Jan. 2013)

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""
import struct
from lantz import Feat, DictFeat, Q_, Action
from lantz.processors import ToQuantityProcessor, FromQuantityProcessor
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


class Generator(object):
    """Agilent N490X BERT Series Pattern Generator Functionality
    """
    __GEN_PATTERNS = {'PRBS7': 'PRBS7',
                      'PRBS10': 'PRBS10',
                      'PRBS11': 'PRBS11',
                      'PRBS15': 'PRBS15',
                      'PRBS23': 'PRBS23',
                      'PRBS31': 'PRBS31',
                      'PRBN7': 'PRBN7',
                      'PRBN10': 'PRBN10',
                      'PRBN11': 'PRBN11',
                      'PRBN13': 'PRBN13',
                      'PRBN15': 'PRBN15',
                      'PRBN23': 'PRBN23',
                      'ZSUB7': 'ZSUB7',
                      'ZSUB10': 'ZSUB10',
                      'ZSUB11': 'ZSUB11',
                      'ZSUB13': 'ZSUB13',
                      'ZSUB15': 'ZSUB15',
                      'ZSUB23': 'ZSUB23',
                      'MDEN7': 'MDEN7',
                      'MDEN10': 'MDEN10',
                      'MDEN11': 'MDEN11',
                      'MDEN13': 'MDEN13',
                      'MDEN15': 'MDEN15',
                      'MDEN23': 'MDEN23',
                      'USER1': 'UPAT1',
                      'USER2': 'UPAT2',
                      'USER3': 'UPAT3',
                      'USER4': 'UPAT4',
                      'USER5': 'UPAT5',
                      'USER6': 'UPAT6',
                      'USER7': 'UPAT7',
                      'USER8': 'UPAT8',
                      'USER9': 'UPAT9',
                      'USER10': 'UPAT10',
                      'USER11': 'UPAT11',
                      'USER12': 'UPAT12',
                      'SEQUENCE': 'SEQ',
                      'USER': 'UPAT',
                      'FILE': 'FIL'}
    __GEN_PATTERNS_NOT_SELECTABLE = ['USER', 'FILE']
                      
    @property
    def generator_patterns(self):
        """A list of available patterns for the generator.
        """
        patterns = list(self.__GEN_PATTERNS.keys())
        for value in self.__GEN_PATTERNS_NOT_SELECTABLE:
            patterns.remove(value)
        return patterns
    
    @Feat(values=__GEN_PATTERNS)
    def generator_pattern(self):
        """The output pattern type (and length).
        
        This command defines the type of pattern being generated. The
        parameter is retained for backwards compatibility and may be one of
        the following:
        
        - PRBS<n> <n> = 7, 10, 11, 15, 23, 31
        - PRBN<n> <n> = 7, 10,11,13, 15, 23
        - ZSUBstitut<n> <n> = 7, 10,11,13, 15, 23
        - UPATtern<n> <n> = 1 through 12
        - MDENsity<n> <n> = 7, 10,11,13, 15, 23
        - FILename, <string>
        - SEQuence
        - PRBS23P
        
        **PRBS23P**
        A new additional special PRBS (2^23-1p). PRBS 2^23-1 named PRBS23P 
        with the polynomial X^23 + X^21 + X^16 + X^8 + X^5 + X^2 + 1.
        
        .. seealso: generator_patterns
        """
        return self.query(":SOUR1:PATT:SEL?")
        
    @generator_pattern.setter
    def generator_pattern(self, value):
        self.send(":SOUR1:PATT:SEL {0}".format(value))
        
    @Feat(values={True: 'CONN', False: 'DISC'})
    def outputs_enabled(self):
        """Enabled state of ALL generator outputs.
        
        Setting to ``False`` sets the voltage at the pattern generator's 
        Data Out, Clock Out, Aux Data Out and Trigger/Ref Clock Out ports to 
        0 V. Setting to ``True`` re-enables the output (to the normal data 
        pattern).
        """
        response = self.query(":OUTP:CENT?")
        if len(response) > 4:
            response = response[0:4]
        response = response.upper()
        return response
        
    @outputs_enabled.setter
    def outputs_enabled(self, value):
        self.send("OUTP:CENT {0}".format(value))
        
    __VOLTAGE_SOURCES = {'data': '1',
                         'aux data': '5',
                         'clock': '2',
                         'trigger': '3:TRIG'}
                         
    @property
    def sources(self):
        """A list of the available sources.
        """
        return list(self.__VOLTAGE_SOURCES.keys())
        
    @DictFeat(units='volts', keys=__VOLTAGE_SOURCES)
    def source_amplitude(self, key):
        """The peak-to-peak value of the source signal in units of Volts (single-ended).
        """
        return float(self.query(":SOUR{0}:VOLT:LEV:IMM:AMPL?".format(key)))
        
    @source_amplitude.setter
    def source_amplitude(self, key, value):
        self.send(":SOUR{0}:VOLT:LEV:IMM:AMPL {1}".format(key, value))
        
    @DictFeat(units='volts', keys=__VOLTAGE_SOURCES)
    def source_offset(self, key):
        """The mean of the high and low DC output level in units of Volts (single-ended).
        """
        return float(self.query(":SOUR{0}:VOLT:LEV:IMM:OFFS?".format(key)))
        
    @source_offset.setter
    def source_offset(self, key, value):
        self.send(":SOUR{0}:VOLT:LEV:IMM:OFFS {1}".format(key, value))
        
    @DictFeat(units='volts', keys=__VOLTAGE_SOURCES)
    def source_high(self, key):
        """The DC high output level in units of Volts (single-ended).
        """
        return float(self.query(":SOUR{0}:VOLT:LEV:IMM:HIGH?".format(key)))
        
    @DictFeat(units='volts', keys=__VOLTAGE_SOURCES)
    def source_low(self, key):
        """The DC low output level in units of Volts (single-ended).
        """
        return float(self.query(":SOUR{0}:VOLT:LEV:IMM:LOW?".format(key)))
    
    #==========================================================================
    # Deemphasis
    #==========================================================================
    __DEEMPHASIS_UNITS = {'dB': 'DB', 
                          '%': 'PERC'}
                          
    @property
    def deemphasis_units(self):
        """A list of the available deemphasis settings unit/mode choices.
        """
        return list(self.__DEEMPHASIS_UNITS.keys())
        
    @property
    def deemphasis_modes(self):
        """A list of the available deemphasis settings unit/mode choices.
        """
        return list(self.__DEEMPHASIS_UNITS.keys())
                                    
    @Feat(values=__DEEMPHASIS_UNITS)
    def deemphasis_unit(self):
        """The unit of the deemphasis values (a.k.a. deemphasis mode).
        
        .. seealso: deemphasis_units
        """
        response = self.query(":OUTP:DEEM:MODE?")
        if len(response) > 4:
            response = response[0:4]
        response = response.upper()
        return response
        
    @Feat(values={True: 1, False: 0})
    def deemphasis_enabled(self):
        """Enabled state of the signal deemphasis feature.
        
        This feature enables/disables an N4916A/B De-Emphasis Signal
        Converter that is connected between the Data Out of the pattern
        generator and the DUT. The command is equivalent to pressing the
        Enable button on selecting the De-Emphasis check box.
        """
        return int(self.query(":OUTP:DEEM:ENAB?"))
        
    @deemphasis_enabled.setter
    def deemphasis_enabled(self, value):
        self.send(":OUTP:DEEM:ENAB {0}".format(value))    
    
    __DEEMPHASIS_TAPS = {'pre-cursor 1': 'PREC',
                         'post-cursor 1': 'POST1',
                         'post-cursor 2': 'POST2'}
    
    @DictFeat(units='dB', keys=__DEEMPHASIS_TAPS)
    def deemphasis(self, key):
        """The deemphasis value for a given setting/cursor (unit := dB).
        
        The new N4916B De-Emphasis Signal Converter can generate a precursor 
        (V4/V3), and two post-cursors (V2/V1, V3/V2). 
        The value is interpreted as dB.
        """
        self.deemphasis_unit = 'dB'
        return float(self.query(":OUTP:DEEM:{0}?".format(key)))
        
    @deemphasis.setter
    def deemphasis(self, key, value):
        self.deemphasis_unit = 'dB'
        self.send(":OUTP:DEEM:{0} {1}".format(key, value))
        
    @DictFeat(keys=__DEEMPHASIS_TAPS, limits=(0, 100))
    def deemphasis_percentage(self, key):
        """The deemphasis value for a given setting/cursor as a percentage.
        
        The new N4916B De-Emphasis Signal Converter can generate a precursor 
        (V4/V3), and two post-cursors (V2/V1, V3/V2). 
        The value is given as %. This CANNOT be set, only read.
        """
        self.deemphasis_unit = '%'
        return float(self.query(":OUTP:DEEM:{0}?".format(key)))
        
    @Action()
    def identify_deemphasis(self):
        """Return IDN string of connected deemphasis unit (if no unit, return ``None``).
        """
        response = self.query(":OUTP:DEEM:IDN?")
        return response if response else None
        
    #==========================================================================
    # Jitter source
    #==========================================================================
    @Feat(values={True: 1, False: 0})
    def jitter_enabled(self):
        """The enabled state of the jitter injection (global).
        
        Enables or disables the jitter generation. Refers to random, bounded
        uncorrelated, periodic, sinusoidal, and external jitter. Has no effect on
        spread spectrum clocking.
        """
        return int(self.query(":SOUR8:GLOB?"))
        
    @jitter_enabled.setter
    def jitter_enabled(self, value):
        self.send(":SOUR8:GLOB {0}".format(value))
        
    @Feat(values={True: 1, False: 0})
    def rj_enabled(self):
        """The enabled state of the random jitter generation.
        
        Random jitter is generated by an internal noise generator. Pure random
        jitter has a Gaussian distribution.
        """
        return int(self.query(":SOUR8:RAND:STAT?"))
        
    @rj_enabled.setter
    def rj_enabled(self, value):
        self.send(":SOUR8:RAND:STAT {0}".format(value))
        
    @Feat(values={True: 1, False: 0})
    def rj_lpf_enabled(self):
        """The enabled state of the random jitter generator Low-Pass Filter.
        
        .. seealso: rj_lpf_type
        """
        return int(self.query(":SOUR8:RAND:FILT:LPAS:STAT?"))
        
    @rj_lpf_enabled.setter
    def rj_lpf_enabled(self, value):
        self.send(":SOUR8:RAND:FILT:LPAS:STAT {0}".format(value))
    
    __RJ_LPF_TYPES = {'100 MHz': 'LP100',
                      '500 MHz': 'LP500'}   
    
    @property
    def rj_lpf_types(self):
        """A list of available Random Jitter Low-Pass Filter types.
        """
        return list(self.__RJ_LPF_TYPES.keys())
    
    @Feat(values=__RJ_LPF_TYPES)
    def rj_lpf_type(self, value):
        """The selected Random Jitter Low-Pass Filter type.
        
        Selects between the 500 MHz (LP500 default) low-pass filter and the
        100 MHz (LP100) low-pass filter.
        
        .. seealso: rj_lpf_types
        """
        return self.query(":SOUR8:RAND:FILT:LPAS:SEL?")
        
    @rj_lpf_type.setter
    def rj_lpf_type(self, value):
        self.send(":SOUR8:RAND:FILT:LPAS:SEL {0}".format(value))
    
    @Feat(values={True: 1, False: 0})
    def rj_hpf_enabled(self):
        """The enabled state of the random jitter generator High-Pass Filter.
        
        Turns the 10 MHz high-pass filter for random jitter on or off.
        """
        return int(self.query(":SOUR8:RAND:FILT:HPAS:STAT?"))
        
    @rj_lpf_enabled.setter
    def rj_hpf_enabled(self, value):
        self.send(":SOUR8:RAND:FILT:HPAS:STAT {0}".format(value))
        
    @Feat(units='UI')
    def rj_amplitude(self):
        """The RMS amplitude of the Random Jitter. (units := UI)
        """
        return float(self.query(":SOUR8:RAND:LEV?"))
        
    @rj_amplitude.setter
    def rj_amplitude(self, value):
        self.send(":SOUR8:RAND:LEV {0}".format(value))
        
    @Feat(read_once=True, units='UI')
    def rj_amplitude_min(self):
        """The minimum value to which the RJ can be set (RMS). (units := UI)
        """
        return float(self.query(":SOUR8:RAND:LEV? MIN"))
        
    @Feat(read_once=True, units='UI')
    def rj_amplitude_max(self):
        """The maximum value to which the RJ can be set (RMS). (units := UI)
        """
        return float(self.query(":SOUR8:RAND:LEV? MAX"))
        
    @Feat()
    def rj_crest_factor(self):
        """The ``crest factor`` of the Random Jitter generator.
        
        The ``crest factor`` is the peak-to-peak amplitude divided by the 
        RMS amplitude of the Random Jitter.
        """
        return float(self.query(":SOUR8:RAND:CFAC?"))
        
    @Feat(units='UI')
    def rj_amplitude_pp(self):
        """The peak-to-peak amplitude of the Random Jitter. Read only. (units := UI)
        """
        return (self.rj_crest_factor * self.rj_amplitude)
        
    
    
    #==========================================================================
    # Logic Level Family
    #==========================================================================    
    __SOURCE_LOGIC_LEVEL_FAMILIES = {'ECL': 'ECL',  # EMITTER-COUPLED LOGIC
                                     'LVPECL': 'LVPECL',  # LOW-VOLTAGE POS. EMITTER-COUPLED LOGIC
                                     'SCFL': 'SCFL',  # SOURCE-COUPLED FET LOGIC
                                     'LVDS': 'LVDS',  # LOW-VOLTAGE DIFFERENTIAL SIGNALING
                                     'CML': 'CML',  # CURRENT-MODE LOGIC
                                     'CUSTOM': 'CUST'}    
    
    __SOURCE_LOGIC_LEVEL_FAMILY_ALIASES = {'': 'CUST',
                                           'CUSTOM': 'CUST'}
    
    @property
    def logic_level_families(self):
        """A list of the available logic level families.
        
        :'ECL': EMITTER-COUPLED LOGIC
        :'LVPECL': LOW-VOLTAGE POS. EMITTER-COUPLED LOGIC
        :'SCFL': SOURCE-COUPLED FET LOGIC
        :'LVDS': LOW-VOLTAGE DIFFERENTIAL SIGNALING
        :'CML': CURRENT-MODE LOGIC
        :'CUSTOM': MANUAL STATES THAT THIS HAS NO EFFECT.
        """
        return list(self.__SOURCE_LOGIC_LEVEL_FAMILIES.keys())
    
    @DictFeat(keys=__VOLTAGE_SOURCES, values=__SOURCE_LOGIC_LEVEL_FAMILIES)
    def source_logic_level_family(self, key):
        """The currently selected logic level family for a specified output source.
        """
        response = self.query(":SOUR{0}:VOLT:LEV:LLEV?".format(key))
        family = response.upper()
        if family in self.__SOURCE_LOGIC_LEVEL_FAMILY_ALIASES:
            family = self.__SOURCE_LOGIC_LEVEL_FAMILY_ALIASES[family]
        return family
    
    @source_logic_level_family.setter
    def source_logic_level_family(self, key, value):
        self.send(":SOUR{0}:VOLT:LEV:LLEV {1}".format(key, value))


class N490X(object):
    """Agilent N490X BERT Series Common Functionality
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
        return self.query(':SYST:VERS?')


class N4903B(object):
    """Agilent J-BERT N4903B Core Functionality
    """      
    pass


class N4903B_TCP(N4903B, N490X, Generator, 
                 ErrorQueueImplementation, 
                 ErrorQueueInstrument, IEEE4882SubsetMixin,
                 IORateLimiterMixin, TCPDriver):
    """Agilent J-BERT N4903B Core Functionality TCP Socket Driver
    """
    #: Encoding to transform string to bytes and back as defined in
    #: http://docs.python.org/py3k/library/codecs.html#standard-encodings
    ENCODING = 'latin1'  # some funky characters this way come.

