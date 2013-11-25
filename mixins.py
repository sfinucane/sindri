# -*- coding: utf-8 -*-
"""sindri.mixins

    A set of mixin classes for augmenting Sindri drivers with common features.
    
    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""
from lantz import Feat, Action
from lantz.errors import InstrumentError

from datetime import datetime, timedelta
from time import sleep
from hashlib import sha256 as chksm
from copy import deepcopy

class IORateLimiterMixin(object):
    """Provide the ability to limit the number of sends and receives per second.
    
    This can be useful for preventing IO flooding at the software level.
    
    NOTE: This should be mixed-in at the level where the Driver class is mixed
    with the implementation code for the device driver. Mixing it in at a
    higher level in the inheritance chain usually causes bad things to happen.
    """
    __time_of_last_io = None  # default, DO NOT CHANGE.
    __io_wait_time = 0.0  # default, DO NOT CHANGE.
    
    @Feat(units='s')
    def io_min_delta(self):
        """The minimum time which must elapse between each send/receive operation (seconds).
        
        Floating point numbers (or equivalent) can be used to set subsecond 
        intervals.
        """
        return self.__io_wait_time
    
    @io_min_delta.setter
    def io_min_delta(self, value):
        self.__io_wait_time = value
    
    def __io_wait(self):
        """Wait until the minimum time between I/O operations has passed.
        
        :return bool: Whether a wait was performed during this call.
        """
        if self.__io_wait_time > 0:
            if self.__time_of_last_io:
                # have we waited long enough before sending again?
                elapsed = datetime.utcnow() - self.__time_of_last_io
                try:                
                    self.log_info(
                        "Elapsed time from previous I/O: {0} s".format(elapsed.total_seconds()))
                except:
                    pass
                min_wait = timedelta(seconds=float(self.__io_wait_time))
                remaining = (min_wait - elapsed).total_seconds()
                if remaining > 0:
                    try:
                        self.log_info(
                            "Pausing for {0} seconds".format(remaining))
                    except:
                        pass
                    sleep(remaining)
                    return True  # did wait
        return False  # did not wait
    
    def send(self, *args, **kwargs):
        self.__io_wait()
        _retval = super().send(*args, **kwargs)
        self.__time_of_last_io = datetime.utcnow()
        return _retval
    
    def recv(self, *args, **kwargs):
        self.__io_wait()
        _retval = super().recv(*args, **kwargs)
        self.__time_of_last_io = datetime.utcnow()
        return _retval


class ErrorQueueInstrument(object):
    """Provide functionality for an instrument with an error queue.
    
    This class implements the abstracted higher-level functionality which is
    suitable for an instrument with an error queue. A developer who wishes to
    use this class as a supertype in an instrument driver inheritance chain
    MUST implement the  ``_query_error`` and ``_interpret_error`` methods.
    
    .. seealso: ``_query_error`` and ``_interpret_error``
    """
    __auto_dequeue_error_delay = 1.0  # seconds, float for subsecond time
    __auto_dequeue_error_enabled = False  # default
    
    def send(self, command, *args, **kwargs):
        """Send command to instrument through driver ``chain``
        
        This link in the chain will dequeue an error from the instrument
        error queue when the ``auto_dequeue_error`` keyword argument is ``True``.
        
        NOTE: If the feature ``auto_dequeue_error_enabled`` is True, then 
        this method will attempt to dequeue an error from the top of the
        instrument error queue immediately after sending the given message.
        
        .. seealso:: the ``send`` method of the supertype.
        """
        if not hasattr(super(), 'send'):
            raise NotImplemented('Super does not have a ``send`` method!')
        try:        
            _retval = super().send(command, *args, **kwargs)
        except:
            raise
        #else:
        if self.auto_dequeue_error_enabled:
            sleep(float(self.auto_dequeue_error_delay.magnitude))  # Quantity, ``Q_``
            self.dequeue_error()
        return _retval
            
    def recv(self, *args, **kwargs):
        """Read a message from instrument through driver ``chain``
        
        .. seealso:: the ``recv`` method of the supertype.
        """
        if not hasattr(super(), 'recv'):
            raise NotImplemented('Super does not have a ``recv`` method!')
        return super().recv(*args, **kwargs)
            
    def query(self, command, *, send_args=(None, None), recv_args=(None, None), **kwargs):
        """Send command to instrument, and read response, through driver ``chain``
        
        NOTE: If the feature ``auto_dequeue_error_enabled`` is True, then 
        this method will attempt to dequeue an error from the top of the
        instrument error queue immediately after performing the entire query.
        
        .. seealso:: the ``query`` method of the supertype.
        """
        if not hasattr(super(), 'query'):
            raise NotImplemented('Super does not have a ``query`` method!')
        
        orig_setting = self.auto_dequeue_error_enabled
        self.auto_dequeue_error_enabled = False
        self.send(command, *send_args)       
        try:
            _response = self.recv(*recv_args)
        except:
            raise
        finally:
            self.auto_dequeue_error_enabled = orig_setting
        #else:
        if self.auto_dequeue_error_enabled:
            sleep(float(self.auto_dequeue_error_delay.magnitude))  # Quantity, ``Q_``
            self.dequeue_error()
        return _response
    
    def _query_error(self):
        """Query an error from the instrument error queue.
        
        This method should simply do whatever is necessary to query an error
        from the instrument queue. This may be as simple as the single line: 
        ``return self.query('SYST:ERR?')``, or more complex!
        
        Some error object processing may be done here, the choice is yours!
        
        :returns: The error (an object, or a sentinel, or just raw...)
        
        .. seealso: ``_interpret_error``
        """
        raise NotImplemented("``_query_error`` has not been implemented!")
        
    def _interpret_error(self, error):
        """Interpret and error (as returned by ``_query_error``).
        
        If you wish to take action (such as raise an exception) based on the
        error, this is the place to do so.
        
        :param error: The error as returned by ``_query_error``.
        :returns: None.
        """
        raise NotImplemented("``_parse_queried_error`` has not been implemented!")
    
    @Action()
    def dequeue_error(self):
        """Retrieve an error from the error queue, and raise if error.
        
        :raises: InstrumentError
        """
        orig_setting = self.auto_dequeue_error_enabled
        self.auto_dequeue_error_enabled = False
        try:
            error = self._query_error()
            self._interpret_error(error)
        except:
            raise
        finally:
            self.auto_dequeue_error_enabled = orig_setting
    
    @Feat(values={True: True, False: False})
    def auto_dequeue_error_enabled(self):
        """Enabled state of the auto dequeue error on send/query feature.
        
        When enabled, the driver will automatically dequeue an error after
        every send/query.
        """
        return self.__auto_dequeue_error_enabled
    
    @auto_dequeue_error_enabled.setter
    def auto_dequeue_error_enabled(self, value):
        self.__auto_dequeue_error_enabled = value
    
    @Feat(units='s')
    def auto_dequeue_error_delay(self):
        """The amount of time to pause between sending and dequeueing an error (seconds).
        """
        return self.__auto_dequeue_error_delay
    
    @auto_dequeue_error_delay.setter
    def auto_dequeue_error_delay(self, value):
        self.__auto_dequeue_error_delay = value


class Verifiable(object):
    """Properties and methods which enable data within an object to be ``verifiable``.
    
    There are two points of ``verification`` that this mixin provides the
    ability to use in a subclass:
        
        - A UTC Timestamp, and ``generate_timestamp`` which provides a method
        for creating a UTC timestamp whenever the Verifiable subclass decides
        that a timestamp is appropriate.
        
        - A checksum property, and ``compute_checksum`` which provides a 
        consistent method of calculating the checksum.
        
    **NOTE:**
    The subclass(es) of this class are responsible for storing the result of 
    ``compute_checksum`` in the ``private`` instance field: ``self.__checksum``
    """
    __utc_stamp = None
    __checksum = None
    
    @property
    def utc_stamp(self):
        return deepcopy(self.__utc_stamp)
    
    def generate_timestamp(self):
        return datetime.utcnow()
        
    @property
    def checksum(self):
        return deepcopy(self.__checksum)

    def compute_checksum(self, data):       
        return chksm(data).digest()

