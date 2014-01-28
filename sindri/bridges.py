# -*- coding: utf-8 -*-
"""sindri.bridges

    A set of servers which allow bridging between interfaces (socket, serial, etc...)
    
    Typically, a bridge will be used to serve a local device to the world as 
    a TCP socket connection. On a remote machine, a TCP version of an 
    instrument driver can then be used to connect to the server and, voila,
    a bridge has been established.
    
    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""

import logging
import socket, socketserver


class TCPHandler(socketserver.StreamRequestHandler):
    """
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def handle(self):
        try:
            while True:
                data = self.rfile.readline()
                logging.debug('%s -> inst: %s', self.client_address[0], data)
                data = str(data, self.ENCODING)
                out = 
                out = bytes(out + self.TERMINATION, self.ENCODING)
                self.wfile.write(out)
                logging.debug('%s <- inst: %s', self.client_address[0], out)
        except socket.error as e:
            if e.errno == 32: # Broken pipe
                logging.info('Client disconnected')
        finally:
            self.finish()


class Bridge(object):
    """
    """
    pass


class BridgeFactory(object):
    """Creates a Bridge object when called.
    """
    def __init__(self, local_driver=None):
        super().__init__()
        if local_driver is None:
            raise ValueError("The local device driver cannot be ``None``.")
        self.local_driver = local_driver
        
    def __call__(self, *args, **kwargs):
        """Create a Bridge object using the arguments provided.
        """
        

