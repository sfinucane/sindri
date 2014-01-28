# -*- coding: utf-8 -*-
"""sindri.errors

    A set of common errors for all Sindri drivers to utilize.
    
    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""
from lantz.errors import InstrumentError

# TODO: tack specific messages onto error messages for tracing!
class SindriError(Exception):
    pass


class UndefinedError(SindriError):
    pass


class UndefinedStorageLocationError(InstrumentError, SindriError):
    pass


class OutputDisabledError(InstrumentError, SindriError):
    pass


class SubsystemError(SindriError):
    pass


class InvalidParentError(SubsystemError):
    pass


class PresetError(SindriError):
    pass


class InvalidPresetError(PresetError):
    pass


class ProtectedPresetError(PresetError):
    pass


class PresetHasUnsavedChangesError(PresetError):
    pass


class NoPresetSelectedError(PresetError):
    pass


class CommunicationError(InstrumentError):
    pass


class UnexpectedResponseFormatError(CommunicationError):
    pass

