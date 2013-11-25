# -*- coding: utf-8 -*-
"""
    sindri.agilent
    ~~~~~~~~~~~~~~~~~~~~~~

    :company: Agilent Technologies
    :description: Electronic and bio-analytical measurement instruments and 
    equipment for measurement and evaluation.
    :website: http://www.agilent.com/

    ----

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""

from .e363xa import E3631A_TCP, E3631A_Serial
from .n77xx import N77XX_TCP, N77XX_USBVisa

__all__ = ['E3631A_TCP', 'E3631A_Serial', 'N77XX_TCP', 'N77XX_USBVisa']
