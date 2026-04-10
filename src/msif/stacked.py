from typing import NamedTuple, Literal, Tuple, TypeAlias
from enum import IntEnum


class Tpc(IntEnum):
    '''
    All TPCs known to the MSIF decoder.
    '''
    SET_REGS_WINDOW = 0b1000
    REGS_WRITE = 0b1011
    REGS_READ = 0b0100
    SET_CMD = 0b1110
    SET_CMD_EX = 0b1001
    READ_LONG_DATA = 0b0010
    WRITE_LONG_DATA = 0b1101
    GET_INT = 0b0111
    READ_SHORT_DATA = 0b0011
    WRITE_SHORT_DATA = 0b1100


TPC_NAMES = {v.value: v.name for v in Tpc}
'Quick look-up of TPC names based on the 4-bit code.'


class TransactionPacket(NamedTuple):
    '''
    Decoded transaction for stacked decoders (output=msif, type=txn).
    '''
    tpc: int
    data: bytes
    crc: int
    crc_ok: bool


PacketType: TypeAlias = Tuple[Literal['txn'], TransactionPacket]
'All supported packet type.'
