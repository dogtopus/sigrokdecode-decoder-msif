from typing import ClassVar, NamedTuple, Dict, List, Literal, Optional, Sequence, Tuple, TypeAlias
from enum import IntEnum, auto


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


class RegisterCommon(IntEnum):
    INT = 0x01
    STA0 = auto()
    STA1 = auto()
    TYPE = auto()

    CATEGORY = 0x06
    CLASS = auto()

    CFG = 0x10


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


class RegAccessFormat:
    RW_ABBR: ClassVar[Dict[Literal['READ', 'WRITE'], str]] = {
        'READ': 'R',
        'WRITE': 'W'
    }
    REG_RW_ABBR: ClassVar[Dict[Literal['READ', 'WRITE'], str]] = {
        'READ': 'RR',
        'WRITE': 'RW'
    }
    RW_GETSET: ClassVar[Dict[Literal['READ', 'WRITE'], str]] = {
        'READ': 'GET',
        'WRITE': 'SET'
    }

    @classmethod
    def list_names(cls, dir_: Literal['READ', 'WRITE']) -> List[str]:
        raise NotImplementedError()

    @classmethod
    def list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
        raise NotImplementedError()


# TODO separate the fields into their own format classes and optionally call
# them here so we won't lose bit decoding of the registers when they get
# accessed individually.
class CommonRegAccessFormat(RegAccessFormat):
    # ECC_FAIL_* means an ECC correction is attempted but failed (more than
    # 1 bit has been corrupted), and ECC_CRCT_* means a single-bit error has
    # been corrected by ECC.
    STA_FLAGS: ClassVar[Sequence[Tuple[int, str]]] = [
        (1 << 0, 'ECC_FAIL_CONFIG'),
        (1 << 1, 'ECC_CRCT_CONFIG'),
        (1 << 2, 'ECC_FAIL_OOB'),
        (1 << 3, 'ECC_CRCT_OOB'),
        (1 << 4, 'ECC_FAIL_DATA'),
        (1 << 5, 'ECC_CRCT_DATA'),
        (1 << 8, 'WR_PROT'),
        (1 << 9, 'SLEEP'),
    ]

    # The memo says that 0xff is MS classic, however none of my MS classic
    # cards have this set to 0xff, instead they all have this set to 0x00,
    # so we assume here that maybe 0xff is some reserved value that was seen
    # on very old MS classic cards.
    TYPES: ClassVar[Dict[int, str]] = {
        0x00: 'MS_CLASSIC',
        0x01: 'MS_PRO',
        0xff: 'UNSET',
    }

    CATEGORIES: ClassVar[Dict[int, str]] = {
        0x00: 'DEFAULT',
        0xff: 'UNSET',
    }

    CLASSES: ClassVar[Dict[int, str]] = {
        0x00: 'DEFAULT',
        0x01: 'ROM',
        0xff: 'UNSET',
    }

    @classmethod
    def list_names(cls, dir_: Literal['READ', 'WRITE']) -> List[str]:
        return [f'{cls.RW_GETSET[dir_]} COMMON', cls.RW_ABBR[dir_]]

    @classmethod
    def list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
        sta0, sta1, type_, unk_0x5, category, class_ = vals
        sta = (sta0 << 8) | sta1
        sta_names = list(name for flag, name in cls.STA_FLAGS if flag & sta == flag)
        sta_str = (' {' + ', '.join(sta_names) + '}') if len(sta_names) != 0 else ''

        type_str = cls.TYPES.get(type_, f'0x{type_:02X}')

        category_str = cls.CATEGORIES.get(category, f'0x{type_:02X}')

        class_str = cls.CLASSES.get(class_, f'0x{class_:02X}')

        return [
            f'{cls.RW_GETSET[dir_]} COMMON {{ STA = 0x{sta:02X}{sta_str}, TYPE = {type_str}, 0x05 = 0x{unk_0x5:02X}, CATEGORY = {category_str}, CLASS = {class_str} }}',
            f'{cls.RW_GETSET[dir_]} COMMON {{ ... }}',
            cls.REG_RW_ABBR[dir_]
        ]


# Doubles as a decoder for GET_INT. Use list_int() for such purpose.
class IntRegAccessFormat(RegAccessFormat):
    INT_FLAGS: ClassVar[Sequence[Tuple[int, str]]] = [
        (1 << 0, 'UNK_CMD'),
        (1 << 5, 'REQ_DATA'),
        (1 << 6, 'ERR'),
        (1 << 7, 'DONE'),
    ]

    @classmethod
    def list_names(cls, dir_: Literal['READ', 'WRITE']) -> List[str]:
        return [f'{cls.RW_GETSET[dir_]} INT', cls.RW_ABBR[dir_]]

    @classmethod
    def _list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes, abbr: Optional[str] = None) -> List[str]:
        int_ = vals[0]
        int_names = list(name for flag, name in cls.INT_FLAGS if flag & int_ == flag)
        int_str = (' { ' + ', '.join(int_names) + ' }') if len(int_names) != 0 else ''

        return [
            f'{cls.RW_GETSET[dir_]} INT = 0x{int_:02X}{int_str}',
            cls.REG_RW_ABBR[dir_] if abbr is None else abbr
        ]

    @classmethod
    def list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
        return cls._list_vals(dir_, vals)

    @classmethod
    def list_int(cls, vals: bytes) -> List[str]:
        return cls._list_vals('READ', vals, abbr='I')
