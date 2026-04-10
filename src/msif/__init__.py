'''
Decodes the link layer protocol of the Memory Stick Interface in 1-bit or 4-bit mode.

Mode can be selected using the bus-width option. If set to auto, the decoder will start in 1-bit mode, and will automatically switch modes if the host issues a sequence of commands to change it.
'''

from .pd import Decoder
