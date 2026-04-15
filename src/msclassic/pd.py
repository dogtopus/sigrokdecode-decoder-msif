from dataclasses import dataclass
from enum import IntEnum, auto
from itertools import chain, zip_longest
from typing import TYPE_CHECKING, ClassVar, Dict, List, Literal, NoReturn, Optional, Self, Sequence, Tuple, Type
from typedsigrokdecode import (
    OUTPUT_ANN,
    AnnotationStream,
    ClassAnnotationPair,
    HasAnnotationRows,
    HasAnnotations,
    HasOptions,
    NameDescList,
    OptionMap,
    StackedDecoder,
)
from msif.stacked import CommonRegAccessFormat, IntRegAccessFormat, PacketType, RegAccessFormat, RegisterCommon, Tpc, TransactionPacket


class Annotation(IntEnum):
    SET_REG = 0
    SET_CMD = auto()
    REG_IO = auto()
    GET_INT = auto()
    DATA_IO = auto()
    W_LENGTH = auto()
    W_SEQ = auto()

    def name_as_id(self) -> str:
        return self.name.lower().replace("_", "-")


def format_annotations(inp: Sequence[Tuple[Annotation, str]]) -> NameDescList:
    return tuple((idx.name_as_id(), desc) for idx, desc in inp)


class RegisterMsClassic(IntEnum):
    '''
    Memory Stick Classic registers.
    See https://dmitry.gr/?r=05.Projects&proj=31.%20Memory%20Stick#_TOC_a7a0800360be942f1bf21be49c186b8c
    '''
    BLK_HI = 0x11
    BLK_MID = auto()
    BLK_LO = auto()
    ACCESSTYP = auto()
    PAGE = auto()
    OOB0 = auto()
    OOB1 = auto()
    OOB2 = auto()
    OOB3 = auto()
    OOB4 = auto()
    OOB5 = auto()
    OOB6 = auto()
    OOB7 = auto()
    OOB8 = auto()


ALL_REG_NAMES = {i.value: i.name for i in chain(RegisterCommon, RegisterMsClassic)}


class AccessType(IntEnum):
    BLOCK = 0x00
    PAGE = 0x20
    OOB = 0x40
    OOB_NO_ECC = 0x80


class Command(IntEnum):
    READ = 0xaa
    PROGRAM = 0x55
    ERASE = 0x99
    STOP = 0x33
    RESET = 0x3c


# This is a common register but the meaning differs across different device
# types (for MS classic, bit 3 needs to be set to enable the 4-bit mode, while
# for MS pro bit 7 needs to be cleared instead).
class CfgRegAccessFormat(RegAccessFormat):
    @classmethod
    def list_names(cls, dir_: Literal['READ', 'WRITE']) -> List[str]:
        return [f'{cls.RW_GETSET[dir_]} CFG', cls.RW_ABBR[dir_]]

    @classmethod
    def list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
        name: str = ''

        if vals[0] & 0x88 == 0x88:
            name = 'MODE_4BIT'
        elif vals[0] & 0x80 == 0x80:
            name = 'MODE_1BIT'
        else:
            name = 'UNK'

        return [f'{cls.RW_GETSET[dir_]} CFG = {name} (0x{vals[0]:02X})', cls.REG_RW_ABBR[dir_]]


class NandIoRegAccessFormat(RegAccessFormat):
    ACCESSTYP: ClassVar[Dict[int, str]] = {
        0x00: 'BLOCK',
        0x20: 'PAGE',
        0x40: 'OOB',
        0x80: 'OOB_NOECC',
    }

    @classmethod
    def list_names(cls, dir_: Literal['READ', 'WRITE']) -> List[str]:
        return [f'{dir_} NANDIO', cls.RW_ABBR[dir_]]

    @classmethod
    def list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
        blk = (vals[0] << 16) | (vals[1] << 8) | vals[2]
        accesstyp = cls.ACCESSTYP.get(vals[3], hex(vals[3]))
        return [f'{dir_} NANDIO {{ BLK = {blk}, PAGE = {vals[4]}, ACCESSTYP = {accesstyp} }}', cls.REG_RW_ABBR[dir_]]


class OobRegAccessFormat(RegAccessFormat):
    @classmethod
    def list_names(cls, dir_: Literal['READ', 'WRITE']) -> List[str]:
        return [f'{cls.RW_GETSET[dir_]} OOB', cls.RW_ABBR[dir_]]

    @classmethod
    def list_vals(cls, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
        oob = (vals[0] << 24) | (vals[1] << 16) | (vals[2] << 8) | vals[3]
        # TODO decode manageFlag and overwriFlag and include them in the first label
        return [f'{dir_} OOB = {oob:08X}', cls.REG_RW_ABBR[dir_]]


REG_ACCESS_FORMAT: Dict[Tuple[int, int], Type[RegAccessFormat]] = {
    (RegisterCommon.STA0, 6): CommonRegAccessFormat,
    (RegisterCommon.CFG, 1): CfgRegAccessFormat,
    (RegisterMsClassic.BLK_HI, 5): NandIoRegAccessFormat,
    (RegisterMsClassic.OOB0, 4): OobRegAccessFormat,
}


def reg_list_names(base: int, size: int, dir_: Literal['READ', 'WRITE']) -> List[str]:
    formatter = REG_ACCESS_FORMAT.get((base, size))
    if formatter is None:
        rr_str = []
        rr_reg_list = ', '.join(ALL_REG_NAMES.get(i, f'0x{i:02X}') for i in range(base, base + size))
        rr_str.append(f'{dir_} {{ {rr_reg_list} }}')
        rr_str.append(f'{dir_} {{ ... }}')
        rr_str.append(RegAccessFormat.RW_ABBR[dir_])
        return rr_str

    return formatter.list_names(dir_)


def reg_list_vals(base: int, size: int, dir_: Literal['READ', 'WRITE'], vals: bytes) -> List[str]:
    formatter = REG_ACCESS_FORMAT.get((base, size))
    if formatter is None:
        rr_rv_list = ', '.join(
            f'{ALL_REG_NAMES.get(a, f'0x{a:02X}')} = 0x{v:02X}'
                for a, v in zip(range(base, base + size), vals)
        )
        return [
            f'{dir_} {{ {rr_rv_list} }}',
            f'{dir_} {{ ... }}',
            RegAccessFormat.REG_RW_ABBR[dir_]
        ]
    
    return formatter.list_vals(dir_, vals)


@dataclass
class RwContext:
    dir_: Optional[Literal['READ', 'WRITE']]
    block: int
    page: int
    access_type: AccessType

    @classmethod
    def from_packet_data(cls, data: bytes) -> Optional[Self]:
        blk = (data[0] << 16) | (data[1] << 8) | data[2]
        if data[3] not in AccessType:
            return None
        access_type = AccessType(data[3])
        page = data[4]

        return cls(dir_=None, block=blk, page=page, access_type=access_type)

    def __str__(self) -> str:
        return f'{self.dir_ + ' ' if self.dir_ is not None else ''}BLK {self.block}, PAGE {self.page}'


class Decoder(
    StackedDecoder[PacketType, NoReturn],
    HasAnnotations,
    HasAnnotationRows,
):
    api_version = 3
    id = 'msclassic'
    name = 'Memory Stick'
    longname = 'Memory Stick Classic'
    desc = "Memory Stick Classic protocol decoder."
    license = "gplv3+"
    inputs = ['msif']
    outputs = []
    tags = ["Memory"]

    annotations = format_annotations(
        [
            (Annotation.SET_REG, 'Set Register'),
            (Annotation.SET_CMD, 'Command'),
            (Annotation.REG_IO, 'Register Access'),
            (Annotation.GET_INT, 'Card Status'),
            (Annotation.DATA_IO, 'Data'),
            (Annotation.W_LENGTH, 'Data Length Mismatch'),
            (Annotation.W_SEQ, 'TPC/Command Sequence Error'),
        ]
    )

    annotation_rows = (
        (
            'data',
            'Data',
            (
                Annotation.SET_REG,
                Annotation.SET_CMD,
                Annotation.REG_IO,
                Annotation.GET_INT,
                Annotation.DATA_IO,
            )
        ),
        (
            'warnings',
            'Warnings',
            (
                Annotation.W_LENGTH,
                Annotation.W_SEQ,
            ),
        ),
    )

    out_ann: AnnotationStream
    
    rrw: Optional[TransactionPacket] = None
    'Register Read/Write address and byte count'

    rd: Optional[RwContext] = None

    def start(self) -> None:
        self.out_ann = self.register(OUTPUT_ANN)

    def reset(self) -> None:
        self.rrw = None
        self.rd = None

    def decode(self, start_sample: int, end_sample: int, data: PacketType, /) -> None:
        t, packet = data
        if t != 'txn':
            return

        if packet.tpc == Tpc.SET_REGS_WINDOW:
            self.annotate_reg_rw(start_sample, end_sample, packet)
            self.rrw = packet
        elif packet.tpc == Tpc.REGS_READ or packet.tpc == Tpc.REGS_WRITE:
            self.annotate_reg_io(start_sample, end_sample, packet)
            if self.rrw is None:
                self.put(start_sample, end_sample, self.out_ann, (
                    Annotation.W_SEQ,
                    ['No prior SET_REGS_WINDOW before register access.'],
                ))
                return
            _, _, wa, wb = self.rrw.data
            # TODO: What about fragmented acess?
            if packet.tpc == Tpc.REGS_WRITE and wa == RegisterMsClassic.BLK_HI and wb == 5:
                self.rd = RwContext.from_packet_data(packet.data)
        elif packet.tpc == Tpc.GET_INT:
            self.annotate_int(start_sample, end_sample, packet)
        elif packet.tpc == Tpc.READ_LONG_DATA or packet.tpc == Tpc.WRITE_LONG_DATA:
            self.annotate_data(start_sample, end_sample, packet)
        elif packet.tpc == Tpc.SET_CMD:
            self.annotate_cmd(start_sample, end_sample, packet)

    def annotate_reg_rw(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        if len(packet.data) != 4:
            self.put(start_sample, end_sample, self.out_ann, (Annotation.W_LENGTH, ['SET_REGS_WINDOW is not 4 bytes long.']))
            return
        ra, rb, wa, wb = packet.data
        rr_str = []
        rw_str = []

        # TODO name common register access patterns (OOB, NANDIO, COMMON, CFG, etc.)

        if rb != 0:
            rr_str.extend(reg_list_names(ra, rb, 'READ'))
        if wb != 0:
            rw_str.extend(reg_list_names(wa, wb, 'WRITE'))

        self.put(
            start_sample,
            end_sample,
            self.out_ann, (
                Annotation.SET_REG,
                [
                    *(' '.join(rwnn for rwnn in rw if rwnn is not None) for rw in zip_longest(rr_str, rw_str)),
                    'S'
                ]
            )
        )

    def annotate_reg_io(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        tpc = Tpc(packet.tpc)

        if self.rrw is None:
            self.put(start_sample, end_sample, self.out_ann, (Annotation.W_LENGTH, [f'{tpc.name} without matching prior SET_REGS_WINDOW.']))
            return
        
        ioa: int
        iob: int
        name: Literal['READ', 'WRITE']

        if tpc == Tpc.REGS_READ:
            ioa, iob = self.rrw.data[0:2]
            name = 'READ'
        elif tpc == Tpc.REGS_WRITE:
            ioa, iob = self.rrw.data[2:4]
            name = 'WRITE'
        else:
            raise TypeError('Invalid TPC for annotate_reg_io. This is a bug.')

        if iob != len(packet.data):
            self.put(start_sample, end_sample, self.out_ann, (Annotation.W_LENGTH, [f'Inconsistent {tpc.name} length.']))
            return

        rv_str = reg_list_vals(ioa, iob, name, packet.data)

        # TODO generate pretty print for common register access patterns (like "READ OOB = C0FBFFFF" or READ NANDIO {BLK = 1, PAGE = 0, ACCESSTYP = 0x20})

        self.put(
            start_sample,
            end_sample,
            self.out_ann, (
                Annotation.REG_IO,
                rv_str,
            )
        )
    
    def annotate_int(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        labels = IntRegAccessFormat.list_int(packet.data)
        self.put(start_sample, end_sample, self.out_ann, (
            Annotation.GET_INT,
            labels,
        ))
    
    def annotate_cmd(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        cmd = packet.data[0]
        is_data_access = cmd in (Command.READ, Command.PROGRAM)
        cmd_str = Command(cmd).name if cmd in Command else f'0x{cmd:02X}'

        self.put(start_sample, end_sample, self.out_ann, (
            Annotation.SET_CMD,
            [f'CMD {cmd_str}', 'C']
        ))

        if self.rd is None and is_data_access:
            self.put(start_sample, end_sample, self.out_ann, (
                Annotation.W_SEQ,
                ['Data access without prior conditions.'],
            ))
            return

        if self.rd is not None and is_data_access:
            self.rd.dir_ = 'READ' if cmd == Command.READ else 'WRITE'

    def annotate_data(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        if self.rd is None:
            self.put(start_sample, end_sample, self.out_ann, (
                Annotation.W_SEQ,
                ['Data access without prior conditions.'],
            ))
            return

        dir_ = 'READ' if packet.tpc == Tpc.READ_LONG_DATA else 'WRITE'
        if self.rd.dir_ != dir_:
            self.put(start_sample, end_sample, self.out_ann, (
                Annotation.W_SEQ,
                ['Data access mode is not consistent with previous observation.'],
            ))
            return

        hexdump = ' '.join(f'{b:02X}' for b in packet.data)

        self.put(start_sample, end_sample, self.out_ann, (
            Annotation.DATA_IO, [f'{str(self.rd)} [ {hexdump} ]', 'D'],
        ))

        if self.rd.access_type == AccessType.BLOCK:
            self.rd.page += 1


if TYPE_CHECKING:
    from typing import reveal_type

    reveal_type(Decoder())
