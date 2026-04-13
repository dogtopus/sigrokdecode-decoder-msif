from enum import IntEnum, auto
from itertools import chain, zip_longest
from typing import TYPE_CHECKING, NoReturn, Optional, Sequence, Tuple
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

from msif.stacked import PacketType, RegisterCommon, Tpc, TransactionPacket


class Annotation(IntEnum):
    SET_REG = 0
    REG_IO = auto()
    W_LENGTH = auto()

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
            (Annotation.REG_IO, 'Register Access'),
            (Annotation.W_LENGTH, 'Data Length Mismatch'),
        ]
    )

    annotation_rows = (
        (
            'data',
            'Data',
            (
                Annotation.SET_REG,
                Annotation.REG_IO,
            )
        ),
        (
            'warnings',
            'Warnings',
            (
                Annotation.W_LENGTH,
            ),
        ),
    )

    out_ann: AnnotationStream
    
    rrw: Optional[TransactionPacket] = None
    'Register Read/Write address and byte count'

    def start(self) -> None:
        self.out_ann = self.register(OUTPUT_ANN)

    def reset(self) -> None:
        self.rrw = None

    def decode(self, start_sample: int, end_sample: int, data: PacketType, /) -> None:
        t, packet = data
        if t != 'txn':
            return

        if packet.tpc == Tpc.SET_REGS_WINDOW:
            self.annotate_reg_rw(start_sample, end_sample, packet)
            self.rrw = packet
        if packet.tpc == Tpc.REGS_READ or packet.tpc == Tpc.REGS_WRITE:
            self.annotate_reg_io(start_sample, end_sample, packet)

    def annotate_reg_rw(self, start_sample: int, end_sample: int, packet: TransactionPacket) -> None:
        if len(packet.data) != 4:
            self.put(start_sample, end_sample, self.out_ann, (Annotation.W_LENGTH, ['SET_REGS_WINDOW is not 4 bytes long.']))
            return
        ra, rb, wa, wb = packet.data
        rr_str = []
        rw_str = []

        # TODO name common register access patterns (OOB, NANDIO, COMMON, CFG, etc.)

        if rb != 0:
            rr_reg_list = ', '.join(ALL_REG_NAMES.get(i, f'0x{i:02X}') for i in range(ra, ra + rb))
            rr_str.append(f'READ {{ {rr_reg_list} }}')
            rr_str.append('READ { ... }')
            rr_str.append('R')
        if wb != 0:
            rw_reg_list = ' '.join(ALL_REG_NAMES.get(i, f'0x{i:02X}') for i in range(wa, wa + wb))
            rw_str.append(f'WRITE {{ {rw_reg_list} }}')
            rw_str.append('WRITE { ... }')
            rw_str.append('W')

        self.put(
            start_sample,
            end_sample,
            self.out_ann, (
                Annotation.SET_REG,
                [
                    *(' '.join(rw) for rw in zip_longest(rr_str, rw_str, fillvalue='')),
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
        name: str

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

        rr_rv_list = ', '.join(f'{ALL_REG_NAMES.get(a, f'0x{a:02X}')} = 0x{v:02X}' for a, v in zip(range(ioa, ioa + iob), packet.data))

        # TODO generate pretty print for common register access patterns (like "READ OOB = C0FBFFFF" or READ NANDIO {BLK = 1, PAGE = 0, ACCESSTYP = 0x20})

        self.put(
            start_sample,
            end_sample,
            self.out_ann, (
                Annotation.REG_IO,
                [
                    f'{name} {{ {rr_rv_list} }}',
                    f'{name} {{ ... }}',
                    'RR' if tpc == Tpc.REGS_READ else 'RW'
                ],
            )
        )


if TYPE_CHECKING:
    from typing import reveal_type

    reveal_type(Decoder())
