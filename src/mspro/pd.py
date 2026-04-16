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


class RegisterMsPro(IntEnum):
    '''
    Memory Stick Pro registers.
    See https://dmitry.gr/?r=05.Projects&proj=31.%20Memory%20Stick#_TOC_8f8157fc09be51bd84664d0f948a486e
    '''
    NUMSEC_HI = 0x11
    NUMSEC_LO = auto()
    ADDR_HI = auto()
    ACCESSTYP = auto()
    ADDR_MIDHI = auto()
    ADDR_MIDLO = auto()
    ADDR_LO = auto()
    PARAM1 = auto()
    PARAM2 = auto()


ALL_REG_NAMES = {i.value: i.name for i in chain(RegisterCommon, RegisterMsPro)}


class AccessType(IntEnum):
    BLOCK = 0x00


class Command(IntEnum):
    FORMAT = 0x10
    READ = 0x20
    WRITE = 0x21
    SLEEP = 0x23
    ATTR = 0x24
    STOP = 0x25
    TRIM = 0x26
    # PS VITA memory card auth commands - not sure how they would work exactly
    # Could be SET_CMD followed by {READ,WRITE}_SHORT_DATA?
    # https://wiki.henkaku.xyz/vita/Memory_Card
    VITA_AUTH_SEED = 0x48  # Mutual auth - set seed / card challenge
    VITA_AUTH_RESP = 0x49  # Mutual auth - get card response + host challenge
    VITA_AUTH_UNLOCK = 0x4a  # Mutual auth - set host response and unlock the card
    VITA_READ_CERT = 0x4b  # Read card certificate (constant but different across cards)


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

        if vals[0] & 0x80 == 0x00:
            name = 'MODE_4BIT'
        elif vals[0] & 0x80 == 0x80:
            name = 'MODE_1BIT'
        else:
            name = 'UNK'

        return [f'{cls.RW_GETSET[dir_]} CFG = {name} (0x{vals[0]:02X})', cls.REG_RW_ABBR[dir_]]


REG_ACCESS_FORMAT: Dict[Tuple[int, int], Type[RegAccessFormat]] = {
    (RegisterCommon.STA0, 6): CommonRegAccessFormat,
    (RegisterCommon.CFG, 1): CfgRegAccessFormat,
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
    section: Optional[Literal['DATA', 'ATTR']]
    lba: int
    count: Optional[int]
    access_type: AccessType

    @classmethod
    def from_packet_data(cls, data: bytes) -> Optional[Self]:
        count_i = (data[0] << 8) | data[1]
        count = None if count_i == 0 else count_i
        if data[3] not in AccessType:
            return None
        access_type = AccessType(data[3])
        lba = (data[2] << 24) | (data[4] << 16) | (data[5] << 8) | data[6]

        return cls(dir_=None, section=None, lba=lba, count=count, access_type=access_type)

    @classmethod
    def from_cmd_ex_data(cls, data: bytes):
        if data[0] not in (Command.READ, Command.WRITE, Command.ATTR):
            return None

        count_i = (data[1] << 8) | data[2]
        count = None if count_i == 0 else count_i
        lba = (data[3] << 24) | (data[4] << 16) | (data[5] << 8) | data[6]
        # Note: ATTR is READ too
        dir_: Literal['READ', 'WRITE'] = 'WRITE' if data[0] == Command.WRITE else 'READ'
        section: Literal['DATA', 'ATTR'] = 'ATTR' if data[0] == Command.ATTR else 'DATA'

        return cls(dir_=dir_, section=section, lba=lba, count=count, access_type=AccessType.BLOCK)

    def __str__(self) -> str:
        return f'{self.dir_ + ' ' if self.dir_ is not None else ''}{self.section + ' ' if self.section is not None else ''}LBA {self.lba}'


class Decoder(
    StackedDecoder[PacketType, NoReturn],
    HasAnnotations,
    HasAnnotationRows,
):
    api_version = 3
    id = 'mspro'
    name = 'MS Pro'
    longname = 'Memory Stick Pro'
    desc = "Memory Stick Pro protocol decoder."
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
        elif packet.tpc == Tpc.GET_INT:
            self.annotate_int(start_sample, end_sample, packet)
        elif packet.tpc == Tpc.READ_LONG_DATA or packet.tpc == Tpc.WRITE_LONG_DATA:
            self.annotate_data(start_sample, end_sample, packet)
        elif packet.tpc == Tpc.SET_CMD:
            self.annotate_cmd(start_sample, end_sample, packet)
            # TODO generate rwcontext based on rrw
        elif packet.tpc == Tpc.SET_CMD_EX:
            self.annotate_cmd_ex(start_sample, end_sample, packet)
            self.rd = RwContext.from_cmd_ex_data(packet.data)

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
        cmd_str = Command(cmd).name if cmd in Command else f'0x{cmd:02X}'

        self.put(start_sample, end_sample, self.out_ann, (
            Annotation.SET_CMD,
            [f'CMD {cmd_str}', 'C']
        ))

    def annotate_cmd_ex(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        cmd = packet.data[0]
        count = (packet.data[1] << 8) | packet.data[2]
        lba = (packet.data[3] << 24) | (packet.data[4] << 16) | (packet.data[5] << 8) | packet.data[6]
        cmd_str = Command(cmd).name if cmd in Command else f'0x{cmd:02X}'
        count_str = f'COUNT = {count}' if count != 0 else 'CONTINUOUS'
        self.put(start_sample, end_sample, self.out_ann, (
            Annotation.SET_CMD,
            [f'CMD {cmd_str} LBA = {lba} {count_str}', 'C']
        ))

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

        self.rd.lba += 1
        if self.rd.count is not None:
            self.rd.count -= 1


if TYPE_CHECKING:
    from typing import reveal_type

    reveal_type(Decoder())
