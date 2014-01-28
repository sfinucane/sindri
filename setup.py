#/usr/bin/env python
# -*- coding: utf-8 -*-
""" setup.py: Sindri distutils setup script.

    :author: Sean Anthony Finucane <s.finucane001@gmail.com>

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""

from distutils.core import setup

setup(name='sindri',
      version='0.1.0a',
      description='Instrument and device drivers, and utilities.',
      author='Sean Anthony Finucane',
      author_email='s.finucane001@gmail.com',
      url='',
      packages=['', 'agilent', 'anritsu', 'artek', 'ieee4882', 'tektronix', 'units'],
     )
