# -*- coding: utf-8 -*-
"""sindri.subsystem

    THIS DOES NOT WORK YET!

    A subsystem, or ``sub-instrument``, model base implementation.
    
    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""
from sindri.errors import InvalidParentError

def check_parent(uut):
    """Determine whether an object is capable of being a parent.
    
    :param uut: The object to test
    
    :raises: InvalidParentError
    """
    if not hasattr(uut, 'send'):
        raise InvalidParentError('No ``send`` method.')
    if not hasattr(uut, 'recv'):
        raise InvalidParentError('No ``recv`` method.')
    if not hasattr(uut, 'query'):
        raise InvalidParentError('No ``query`` method.')


class Subsystem(object):
    """Base class for subsystems.
    
    A subsystem is, essentially, an instrument which exists within another
    instrument. The subsystem has ``Feats`` and ``Actions`` as any instrument
    would, but is meant to be embedded within another instrument as a standard
    property. Such a property SHOULD be read-only, and should be instantiated
    with the main instrument instance.
    """
    def __init__(self, parent, *args, **kwargs):
        """Initialize this subsystem/sub-instrument.
        
        Please pass an appropriate parent, namely, one that has the ability
        to ``send``, ``recv``, and ``query``.
        """
        super().__init__(*args, **kwargs)
        check_parent(parent)
        self.__parent = parent
        
    def __getattr__(self, attr):
        try:
            try:
                return self.__dict__[attr]
            except:
                return getattr(super(), attr)
        except:
            return getattr(self.__parent, attr)
    
    
