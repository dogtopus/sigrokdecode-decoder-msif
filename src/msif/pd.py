from enum import IntEnum, auto
from typing import TYPE_CHECKING, ClassVar, Literal, Sequence, Tuple, TypeAlias, TypedDict, Union
from typedsigrokdecode import OUTPUT_ANN, AnnotationStream, BottomDecoder, ChannelCondition, HasAnnotationRows, HasAnnotations, HasChannels, HasOptionalChannels, HasOptions, NameDescList, OptionMap


PythonPacket: TypeAlias = None
StateLiteral: TypeAlias = Literal['IDLE', 'TPC', 'OUT_DATA', 'OUT_RDY', 'IN_RDY', 'IN_DATA', 'IN_DATA2']


class IdName(TypedDict):
    id: str
    name: str


class Channel(IntEnum):
    SDIO = 0
    SCLK = auto()
    BS = auto()
    DATA1 = auto()
    DATA2 = auto()
    DATA3 = auto()

    def to_idname(self) -> IdName:
        return {'id': self.name.lower(), 'name': self.name}


class Annotation(IntEnum):
    START = 0
    TPC = auto()
    DATA = auto()
    DATA_RDY = auto()
    W_CRC = auto()
    W_FORMAT = auto()

    def name_as_id(self) -> str:
        return self.name.lower().replace('_', '-')


CRC_TAB = (
    0x0000, 0x8005, 0x800f, 0x000a, 0x801b, 0x001e, 0x0014, 0x8011,
    0x8033, 0x0036, 0x003c, 0x8039, 0x0028, 0x802d, 0x8027, 0x0022,
    0x8063, 0x0066, 0x006c, 0x8069, 0x0078, 0x807d, 0x8077, 0x0072,
    0x0050, 0x8055, 0x805f, 0x005a, 0x804b, 0x004e, 0x0044, 0x8041,
    0x80c3, 0x00c6, 0x00cc, 0x80c9, 0x00d8, 0x80dd, 0x80d7, 0x00d2,
    0x00f0, 0x80f5, 0x80ff, 0x00fa, 0x80eb, 0x00ee, 0x00e4, 0x80e1,
    0x00a0, 0x80a5, 0x80af, 0x00aa, 0x80bb, 0x00be, 0x00b4, 0x80b1,
    0x8093, 0x0096, 0x009c, 0x8099, 0x0088, 0x808d, 0x8087, 0x0082,
    0x8183, 0x0186, 0x018c, 0x8189, 0x0198, 0x819d, 0x8197, 0x0192,
    0x01b0, 0x81b5, 0x81bf, 0x01ba, 0x81ab, 0x01ae, 0x01a4, 0x81a1,
    0x01e0, 0x81e5, 0x81ef, 0x01ea, 0x81fb, 0x01fe, 0x01f4, 0x81f1,
    0x81d3, 0x01d6, 0x01dc, 0x81d9, 0x01c8, 0x81cd, 0x81c7, 0x01c2,
    0x0140, 0x8145, 0x814f, 0x014a, 0x815b, 0x015e, 0x0154, 0x8151,
    0x8173, 0x0176, 0x017c, 0x8179, 0x0168, 0x816d, 0x8167, 0x0162,
    0x8123, 0x0126, 0x012c, 0x8129, 0x0138, 0x813d, 0x8137, 0x0132,
    0x0110, 0x8115, 0x811f, 0x011a, 0x810b, 0x010e, 0x0104, 0x8101, 
    0x8303, 0x0306, 0x030c, 0x8309, 0x0318, 0x831d, 0x8317, 0x0312,
    0x0330, 0x8335, 0x833f, 0x033a, 0x832b, 0x032e, 0x0324, 0x8321,
    0x0360, 0x8365, 0x836f, 0x036a, 0x837b, 0x037e, 0x0374, 0x8371,
    0x8353, 0x0356, 0x035c, 0x8359, 0x0348, 0x834d, 0x8347, 0x0342,
    0x03c0, 0x83c5, 0x83cf, 0x03ca, 0x83db, 0x03de, 0x03d4, 0x83d1,
    0x83f3, 0x03f6, 0x03fc, 0x83f9, 0x03e8, 0x83ed, 0x83e7, 0x03e2,
    0x83a3, 0x03a6, 0x03ac, 0x83a9, 0x03b8, 0x83bd, 0x83b7, 0x03b2,
    0x0390, 0x8395, 0x839f, 0x039a, 0x838b, 0x038e, 0x0384, 0x8381,
    0x0280, 0x8285, 0x828f, 0x028a, 0x829b, 0x029e, 0x0294, 0x8291,
    0x82b3, 0x02b6, 0x02bc, 0x82b9, 0x02a8, 0x82ad, 0x82a7, 0x02a2,
    0x82e3, 0x02e6, 0x02ec, 0x82e9, 0x02f8, 0x82fd, 0x82f7, 0x02f2,
    0x02d0, 0x82d5, 0x82df, 0x02da, 0x82cb, 0x02ce, 0x02c4, 0x82c1,
    0x8243, 0x0246, 0x024c, 0x8249, 0x0258, 0x825d, 0x8257, 0x0252,
    0x0270, 0x8275, 0x827f, 0x027a, 0x826b, 0x026e, 0x0264, 0x8261,
    0x0220, 0x8225, 0x822f, 0x022a, 0x823b, 0x023e, 0x0234, 0x8231,
    0x8213, 0x0216, 0x021c, 0x8219, 0x0208, 0x820d, 0x8207, 0x0202,
)


def format_annotations(inp: Sequence[Tuple[Annotation, str]]) -> NameDescList:
    return tuple((idx.name_as_id(), desc) for idx, desc in inp)


def crc16(data: memoryview) -> int:
    crc = 0

    for b in data:
        crc = ((crc << 8) ^ CRC_TAB[b ^ (crc >> 8)]) & 0xffff
    
    return crc


class Decoder(BottomDecoder[PythonPacket], HasOptions, HasChannels, HasOptionalChannels, HasAnnotations, HasAnnotationRows):
    api_version = 3
    id = 'msif'
    name = 'MSIF'
    longname = 'Memory Stick Interface'
    desc = 'Annotate the data transmission of Memory Stick'
    license = 'gplv3+'
    inputs = ['logic']
    outputs = []
    tags = ['Memory']
    options = (
        {
            'id': 'bus-width',
            'desc': 'Bus width',
            'default': 'auto',
            'values': ('auto', '1-bit', '4-bit'),
        },
    )
    # These must be in the exact same order as the IntEnum
    channels = (
        {**Channel.SDIO.to_idname(), 'desc': 'Data line 0'},
        {**Channel.SCLK.to_idname(), 'desc': 'Clock line'},
        {**Channel.BS.to_idname(), 'desc': 'Bus state'},
    )
    optional_channels = (
        {**Channel.DATA1.to_idname(), 'desc': 'Data line 1'},
        {**Channel.DATA2.to_idname(), 'desc': 'Data line 2'},
        {**Channel.DATA3.to_idname(), 'desc': 'Data line 3'},
    )
    annotations = format_annotations([
        (Annotation.START, 'Start Condition'),
        (Annotation.TPC, 'Transfer Protocol Command'),
        (Annotation.DATA, 'Data'),
        (Annotation.DATA_RDY, 'Data Ready'),
        (Annotation.W_CRC, 'CRC Error'),
        (Annotation.W_FORMAT, 'Invalid data format'),
    ])
    annotation_rows = (
        ('symbols', 'Protocol Symbols', (
            Annotation.START,
            Annotation.TPC,
            Annotation.DATA,
            Annotation.DATA_RDY,
        )),
        ('warnings', 'Warnings', (
            Annotation.W_CRC,
            Annotation.W_FORMAT,
        ))
    )

    SCLK_POSEDGE: ClassVar[ChannelCondition] = {Channel.SCLK: 'r'}

    out_ann: AnnotationStream

    state: StateLiteral = 'IDLE'
    bits: Literal[1, 4] = 1
    allow_mode_switch: bool = False

    def start(self) -> None:
        self.out_ann = self.register(OUTPUT_ANN)

        options: OptionMap = self.get_options()

        if options['bus-width'] == 'auto':
            self.allow_mode_switch = True
        elif options['bus-width'] == '4-bit':
            self.bits = 4

    def handle_bit_switch(self, regs: bytes, val: bytes) -> bool:
        if not self.allow_mode_switch:
            return False

        wbase, wsize = regs[2], regs[3]
        if wbase == 0 and wsize == 0:
            return False
        wend = wbase + wsize
        if wbase <= 0x10 < wend:
            val_offset = 0x10 - wbase
            if val_offset >= len(val):
                return False
            cfg = val[val_offset]
            if cfg & 0x80:
                self.bits = 1
            else:
                self.bits = 4
            return True
        return False

    def put_data(self, start: int, end: int, dir_: Literal['IN', 'OUT'], data: Union[bytes, bytearray]):
        if len(data) < 3:
            self.put(start, end, self.out_ann, (Annotation.W_FORMAT, ['Data too short.']))
            return
        payload = memoryview(data)[:-2]
        crc_expected = (data[-2] << 8) | data[-1]
        crc_actual = crc16(payload)
        crc_ok = 'OK' if crc_expected == crc_actual else 'NG'
        self.put(start, end, self.out_ann, (Annotation.DATA, [f'{dir_}: {payload.hex()} CRC: {crc_expected:04x} ({crc_ok})', dir_, dir_[0]]))
        if crc_ok != 'OK':
            self.put(start, end, self.out_ann, (Annotation.W_CRC, [f'CRC mismatch (exp.: {crc_expected:04x} got: {crc_actual:04x})']))

    def decode4(self) -> bool:
        next_state: StateLiteral = 'IDLE'
        shift: int = 0
        data: bytearray = bytearray()
        data_count: int = 0
        ann_start: int = 0
        seen_rdy: bool = False
        tpc: int = 0

        regs: bytes = b'\x00\x00\x00\x00'
        val: bytes = b''

        pulse_count = 0

        while True:
            prev_pulse = self.samplenum
            latched = self.wait(self.SCLK_POSEDGE)
            if latched is None:
                return False
            curr_pulse = self.samplenum

            # Finish off state changes
            if self.state != next_state:
                if self.state == 'IDLE':
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.START, ['Start Condition', 'Start', 'S']))
                elif self.state == 'TPC':
                    tpc = shift >> 12
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.TPC, [f'TPC: {tpc:04b}', 'TPC', 'T']))
                elif self.state == 'OUT_DATA':
                    self.put_data(ann_start, curr_pulse, 'OUT', data)
                elif self.state == 'IN_RDY':
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.DATA_RDY, ['RDY', 'R']))
                elif self.state == 'OUT_RDY':
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.DATA_RDY, ['ACK', 'A']))
                    # Bit mode switch hook
                    if tpc == 0b1000:
                        regs = bytes(data[:4])
                    elif tpc == 0b1011:
                        val = bytes(data[:-2])
                        if self.handle_bit_switch(regs, val):
                            return True
                    else:
                        regs = b'\x00\x00\x00\x00'
                        val = b''
                if self.state != 'IN_DATA':
                    ann_start = curr_pulse
                self.state = next_state

            shift <<= 4
            shift &= 0xffff
            shift |= (
                (latched[Channel.DATA3] << 3) |
                (latched[Channel.DATA2] << 2) |
                (latched[Channel.DATA1] << 1) |
                latched[Channel.SDIO]
            )

            if self.state == 'IDLE' and latched[Channel.BS] == 1:
                if pulse_count == 0:
                    ann_start = curr_pulse
                pulse_count += 1
                if pulse_count == 4:
                    next_state = 'TPC'
                    pulse_count = 0
            elif self.state == 'TPC' and latched[Channel.BS] == 0:
                pulse_count += 1
                if pulse_count == 2:
                    if shift & 0x8000:
                        next_state = 'OUT_DATA'
                    else:
                        next_state = 'IN_RDY'
                    data_count = 0
                    data.clear()
                    seen_rdy = False
                    pulse_count = 0
            elif self.state == 'OUT_DATA':
                if pulse_count == 0:
                    data_count += 4
                    if data_count % 8 == 0:
                        data.append(shift & 0xff)
                if latched[Channel.BS] == 1:
                    pulse_count += 1
                    if pulse_count == 4:
                        next_state = 'OUT_RDY'
                        pulse_count = 0
            elif self.state == 'IN_RDY':
                if not seen_rdy and not shift & 1:
                    seen_rdy = True
                    ann_start = curr_pulse
                if latched[Channel.BS] == 1:
                    pulse_count += 1
                    if pulse_count == 2:
                        next_state = 'IN_DATA'
                        pulse_count = 0
            elif self.state == 'OUT_RDY':
                if not seen_rdy and not shift & 1:
                    seen_rdy = True
                    ann_start = curr_pulse
                if latched[Channel.BS] == 0:
                    pulse_count += 1
                    if pulse_count == 2:
                        next_state = 'IDLE'
                        pulse_count = 0
            elif self.state == 'IN_DATA' or self.state == 'IN_DATA2':
                # Commit data on the second clock since no other clock exists
                data_count += 4
                if data_count % 8 == 0:
                    data.append(shift & 0xff)
                if latched[Channel.BS] == 0:
                    next_state = 'IN_DATA2' if self.state == 'IN_DATA' else 'IDLE'
                    if next_state == 'IDLE':
                        self.put_data(ann_start, curr_pulse, 'IN', data)

    def decode1(self) -> bool:
        '''
        1-bit mode decoder.
        '''
        next_state: StateLiteral = 'IDLE'
        shift: int = 0
        data: bytearray = bytearray()
        data_count: int = 0
        ann_start: int = 0
        seen_rdy: bool = False
        tpc: int = 0

        regs: bytes = b'\x00\x00\x00\x00'
        val: bytes = b''

        while True:
            prev_pulse = self.samplenum
            latched = self.wait(self.SCLK_POSEDGE)
            if latched is None:
                return False
            curr_pulse = self.samplenum

            # Finish off state changes
            if self.state != next_state:
                if self.state == 'IDLE':
                    self.put(prev_pulse, curr_pulse, self.out_ann, (Annotation.START, ['Start Condition', 'Start', 'S']))
                elif self.state == 'TPC':
                    tpc = shift >> 4
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.TPC, [f'TPC: {tpc:04b}', 'TPC', 'T']))
                elif self.state == 'OUT_DATA':
                    self.put_data(ann_start, curr_pulse, 'OUT', data)
                elif self.state == 'IN_RDY':
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.DATA_RDY, ['RDY', 'R']))
                elif self.state == 'OUT_RDY':
                    self.put(ann_start, curr_pulse, self.out_ann, (Annotation.DATA_RDY, ['ACK', 'A']))
                    # Bit mode switch hook
                    if tpc == 0b1000:
                        regs = bytes(data[:4])
                    elif tpc == 0b1011:
                        val = bytes(data[:-2])
                        if self.handle_bit_switch(regs, val):
                            return True
                    else:
                        regs = b'\x00\x00\x00\x00'
                        val = b''
                elif self.state == 'IN_DATA':
                    self.put_data(ann_start, curr_pulse, 'IN', data)
                ann_start = curr_pulse
                self.state = next_state

            shift <<= 1
            shift &= 0xff
            shift |= latched[Channel.SDIO]

            # State transitions
            if self.state == 'IDLE' and latched[Channel.BS] == 1:
                next_state = 'TPC'
            elif self.state == 'TPC' and latched[Channel.BS] == 0:
                if shift & 0x80:
                    next_state = 'OUT_DATA'
                else:
                    next_state = 'IN_RDY'
                data_count = 0
                data.clear()
                seen_rdy = False
            elif self.state == 'OUT_DATA':
                data_count += 1
                if data_count % 8 == 0:
                    data.append(shift)
                if latched[Channel.BS] == 1:
                    next_state = 'OUT_RDY'
            elif self.state == 'IN_RDY':
                if not seen_rdy and not shift & 1:
                    seen_rdy = True
                    ann_start = curr_pulse
                if latched[Channel.BS] == 1:
                    next_state = 'IN_DATA'
            elif self.state == 'OUT_RDY':
                if not seen_rdy and not shift & 1:
                    seen_rdy = True
                    ann_start = curr_pulse
                if latched[Channel.BS] == 0:
                    next_state = 'IDLE'
            elif self.state == 'IN_DATA':
                data_count += 1
                if data_count % 8 == 0:
                    data.append(shift)
                if latched[Channel.BS] == 0:
                    next_state = 'IDLE'

    def decode(self, /) -> None:
        while True:
            if self.bits == 1:
                if not self.decode1():
                    break
            elif self.bits == 4:
                if not self.decode4():
                    break

    def reset(self) -> None:
        self.state = 'IDLE'
        self.bits = 1
        self.allow_mode_switch = False


if TYPE_CHECKING:
    from typing import reveal_type
    reveal_type(Decoder())
