# -*- coding: utf-8 -*-
"""
"""

from ..mixins import Verifiable
from sindri.errors import (SindriError, UnexpectedResponseFormatError)
from copy import deepcopy


class InvalidBlockFormatError(SindriError):
    pass


class NeitherBlockNorDataError(ValueError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.message += (
            "(You need to provide either a binary block, or binary data!)" )


class ArbitraryBlock(Verifiable):
    """IEEE 488.2 general ``arbitrary`` block of binary data.
    
    **Immutable**    
    
    ```
    IEEE-488.2 defines two different binary standards for file transfer: 
    ``Definite Length Arbitrary Block`` and ``Indefinite Length Arbitrary 
    Block``. The first one starts with a # sign followed by one-number that 
    indicates the number of digits of the byte counts and then the actual 
    number of bytes that precedes the real binary data. The format could be 
    ``#x1234...`` and is the most commonly used binary format in GPIB 
    instruments. The later starts with  ``#0`` and ends with a new line 
    followed by EOI. It usually has the format of ``#0...LF+EOI``. Some 
    instrument may simply return the raw binary data and users are responsible 
    to find a properly way to define the buffer size for accepting the data 
    presented by the GPIB output buffer.
    ```
    :source: https://docs.google.com/document/preview?hgd=1&id=11AsY2WixTCI0_1at-wT3YP9JeLwjFl7uFuNGxlHI6ec
    
    **NOTE:**
    The above source needs to be fully determined, or changed to the IEEE 488.2
    standard itself!
    """
    __block = None
    __data = None
    __block_id = None
    
    def __init__(self, block=None, block_id=None, data=None):
        """Initialize a block instance.
        
        When creating an instance: (a) if the binary block is provided to
        the constructor, then the data is determined from the block; (b) if
        the data (bytes) is provided to the constructor, then the binary
        block is generated (header information, etc.).
        
        :param: block
        :type str:
            - The binary block, as read from the bus (raw, bytes).
            
        :param: block_id
            - An optional block identifier, of any type.
            
        :param: data
            - The binary data, without the block header.
        """
        if block:
            self.__block = deepcopy(block)
            self.__data_slice = self._get_data_slice(self.__block)
        elif data:
            self.__block = self._create_block(data)
            self.__data_slice = self._get_data_slice(self.__block)
        else:
            raise NeitherBlockNorDataError()
        
        self.__block_id = block_id
        self.__utc_stamp = self.generate_timestamp()
        self.__checksum = self.compute_checksum(self.data)

    def __str__(self):
        return "<IEEE488_BINBLOCK>{0}</IEEE488_BINBLOCK>".format(repr(self.__block))
        
    def __getitem__(self, index):
        return deepcopy(self.__block[index])
    
    def _get_data_slice(self, block):
        """Slice the meaningful binary bytes (data) from the block.
        
        **Abstract**
        
        :returns: Data slice, to be used on the binary block.
        :type slice:
        """
        raise NotImplemented("Attempted to use abstract method: '_get_data_slice'!")
        
    def _create_block(self, data):
        """Construct a binary block with the given data as the payload.
        
        **Abstract**
        
        :returns: A raw binary block which contains the given payload data.
        :type bytes:
        """
        raise NotImplemented("Attempted to use abstract method: '_create_block'!")
    
    @property
    def raw(self):
        """The raw binary block.
        """
        return self.__block
    
    @property
    def identifier(self):
        """An arbitrary means of identifying this block.
        """
        return self.__block_id
    
    @property
    def data(self):
        """The payload binary data contained within the binary block.
        """
        return self.raw[self.__data_slice]


class DefiniteLengthBlock(ArbitraryBlock):
    """IEEE 488.2 Definite Length Arbitrary Binary Data Block
    
    This sort of block starts with a # sign followed by one-number that 
    indicates the number of digits of the byte counts and then the actual 
    number of bytes that precedes the real binary data. The format could be 
    ``#x1234...`` and is the most commonly used binary format in GPIB 
    instruments.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    # override
    def _get_data_slice(self, block):
        """Slice the meaningful binary bytes (data) from the block.
        
        :returns: Data slice, to be used on the binary block.
        :type slice:
        """
        # First character should be "#".
        pound = block[0:1]
        if pound != b'#':
            raise InvalidBlockFormatError(self.identifier)
        # Second character is number of following digits for length value.
        length_digits = block[1:2]
        data_length = block[2:int(length_digits)+2]
        # from the given data length, and known header length, we get indices:
        data_begin = int(length_digits) + 2  # 2 for the '#' and digit count
        data_end = data_begin + int(data_length)
        # Slice the data from the block:
        sData = slice(data_begin, data_end)
        return sData

    # override
    def _create_block(self, data):
        """Construct a binary block with the given data as the payload.
        
        :returns: A raw binary block which contains the given payload data.
        :type bytes:
        """
        # format is: b'#<length_digits><length><payload>'
        length = len(data)
        length_digits = len(str(length))
        header_string = '#' + str(length_digits) + str(length)
        return bytes(header_string.encode('latin1')) + data


class IndefiniteLengthBlock(ArbitraryBlock):
    """IEEE 488.2 Indefinite Length Arbitrary Binary Data Block
    
    This sort of block starts with  ``#0`` and ends with a new line 
    followed by EOI. It usually has the format of ``#0...LF+EOI``.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    # override
    def _get_data_slice(self, block):
        """Slice the meaningful binary bytes (data) from the block.
        
        :returns: Data slice, to be used on the binary block.
        :type slice:
        """
        raise NotImplemented()

    # override
    def _create_block(self, data):
        """Construct a binary block with the given data as the payload.
        
        :returns: A raw binary block which contains the given payload data.
        :type bytes:
        """
        raise NotImplemented()


def read_definite_length_block(raw_recv, block_id=None,
                               recv_termination=None, recv_chunk=None):
    """Read an IEEE 488.2 definite length block, using given raw receive function.
    
    The signature of ``raw_recv`` (the raw receive function) should be:
        - ``bytes = raw_recv(nbytes)``
    Where ``nbytes`` is the number of bytes to read for that call.
    
    :param: raw_recv
    :type function:    
    
    :param: block_id
    :type any:
    :description: An arbitrary block identifier.
    
    :param: recv_termination
    :type string/bytes:
    
    :param: recv_chunk
    :type int:
    
    :returns: The definite length binary block.
    :type DefiniteLengthBlock:
    """
    receive_chunk = recv_chunk
    receive_termination = recv_termination
    # we are expecting an IEEE 488.2 Arbitrary Binary Block
    pound = raw_recv(1)
    if pound != b'#':
        raise UnexpectedResponseFormatError(
            "Expected ``IEEE 488.2 Binary Block``! " +
            "Read: ``{0}``. ".format(pound) +
            "Remaining message data left in buffer.")
        
    ndigits = raw_recv(1)
    block_length = None
    if ndigits not in [b'1', b'2', b'3', b'4', 
                       b'5', b'6', b'7', b'8', b'9']:
        raise UnexpectedResponseFormatError(
            "Expected ``IEEE 488.2 Binary Block``! " +
            "Read: ``{0}{1}``. ".format(pound, ndigits) +
            "Remaining message data left in buffer.")
    elif ndigits in [b'0']:
        block_length = b''
    else:
        # read the block length (ndigit-wide ascii integer)
        block_length = raw_recv(int(ndigits))
    
    data = b''
    if block_length:
        bytes_remaining = int(block_length)
        if not receive_chunk:
            receive_chunk = bytes_remaining
        
        while bytes_remaining > 0:
            reach = min(bytes_remaining, receive_chunk)
            received_data = raw_recv(reach)
            bytes_remaining -= len(received_data)
            data += received_data
    
    if receive_termination:
        # clear trailing term chars
        raw_recv(len(receive_termination))
    
    block = pound + ndigits + block_length + data
    
    return DefiniteLengthBlock(block=block, block_id=block_id)

