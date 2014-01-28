# -*- coding: utf-8 -*-
"""
    sindri.anritsu.common
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements functionality which is commonly found in Anritsu instruments.

    Sources::

        - Anritsu Corporation `link <http://www.anritsu.com>`_

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""

import re
from lantz.errors import InstrumentError

class ErrorQueueImplementation():
    """Provide functionality for Anritsu instruments with error queues.
    
    Typically, a driver developer will mix this class into the inheritance
    chain at a lower-level in the hierarchy than the 
    ``sindri.mixins.ErrorQueueInstrument`` mixin class. This class provides
    concrete implementations for the abstract portions of the aforementioned.
    
    .. seealso: sindri.mixins.ErrorQueueInstrument
    """
    _error_regex = re.compile(r'^(?P<error_code>.*?),(?P<error_msg>.*)$')
    
    #ErrorQueueInstrument:
    def _query_error(self):
        """Get an error from the instrument's error queue.
        """
        return self.query('SYST:ERR?')
    
    #ErrorQueueInstrument:
    def _interpret_error(self, error):
        """Intepret an error string, as returned from the instrument.
        
        :raises: InstrumentError
        """
        #Some instruments only return a simple '0' string to indicate no error!
        if error in ['+0', '0', '', 0, False, None]:
            error = '0,No Error'
        _error_code, _error_msg = self._error_regex.match(error).groups()
        _error_code = int(_error_code)
        if _error_code:
            raise InstrumentError(
                "ERROR {0}: {1}".format(_error_code, _error_msg.strip('"')))
