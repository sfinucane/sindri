# -*- coding: utf-8 -*-
"""
    sindri.anritsu.mp1800a
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Implements the drivers to control an Anritsu MP1800A SQA Mainframe

    MP1800A Mainframe Option Modules::
    
        - TODO: FILL THIS OUT

    Sources::

        - Anritsu Corporation `link <http://www.anritsu.com>`_

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
    
"""

from lantz import Feat, DictFeat, Q_, Action
from sindri.mixins import IORateLimiterMixin, ErrorQueueInstrument
from lantz.network import TCPDriver
from lantz.errors import InstrumentError
from .common import ErrorQueueImplementation
from .mx180000a import MX180000A, IEEE4882SubsetMixin

class MP1800A(object):
    pass


class MP1800A_TCP(MX180000A, ErrorQueueImplementation, ErrorQueueInstrument, 
                  IEEE4882SubsetMixin, 
                  IORateLimiterMixin, TCPDriver):
    pass

