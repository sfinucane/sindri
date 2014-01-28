#/usr/bin/env python
# -*- coding: utf-8 -*-
""" setup.py: Sindri distutils setup script.

    :author: Sean Anthony Finucane <s.finucane001@gmail.com>

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""

#try:
#    from setuptools import setup
#except ImportError:
#    from distutils.core import setup
from setuptools import setup, find_packages

import os
import sys
import codecs


def read(filename):
    return codecs.open(filename, encoding='utf-8').read()

# the long description breaks the ability to install package...
#long_description = '\n\n'.join([read('README.rst'),
#                                read('AUTHORS.rst')])

#__doc__ = long_description

# distutils needed this cruft:
#folder = os.path.dirname(os.path.abspath(__file__))
#folder = os.path.join(folder, 'sindri')
#paths = os.listdir(folder)

requirements = []

# distutils needed this cruft:
#subpackages = [path for path in paths
#               if os.path.isdir(os.path.join(folder, path))
#               and os.path.exists(os.path.join(folder, path, '__init__.py'))]

setup(name='sindri',
      version='0.1.0a',
      description='Instrument and device drivers, and utilities.',
      author='Sean Anthony Finucane',
      author_email='s.finucane001@gmail.com',
      url='',
#      more distutils cruft:
#      packages=['sindri'] + 
#               ['sindri.' + package for package in subpackages],
      packages=find_packages(),
      include_package_data=True,
      install_requires=['Lantz>=0.3'] + requirements,
      platforms='any',
     )
