from collections import deque
from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Dict,
    Iterable,
    List,
    Literal,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    TypeAlias,
    TypeVar,
    TypedDict,
    Union,
)
from typedsigrokdecode import (
    OUTPUT_ANN,
    OUTPUT_PYTHON,
    AnnotationStream,
    BottomDecoder,
    ChannelCondition,
    ClassAnnotationPair,
    HasAnnotationRows,
    HasAnnotations,
    HasChannels,
    HasOptionalChannels,
    HasOptions,
    NameDescList,
    OptionMap,
    PythonStream,
)
from .stacked import TPC_NAMES, PacketType, TransactionPacket
from itertools import groupby, islice, pairwise


StateLiteral: TypeAlias = Literal[
    "IDLE", "TPC", "OUT_DATA", "OUT_RDY", "IN_RDY", "IN_DATA"
]


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
        return {"id": self.name.lower(), "name": self.name}


class Annotation(IntEnum):
    TPC = 0
    DATA = auto()
    DATA_RDY = auto()
    W_CRC = auto()
    W_FORMAT = auto()
    S_START = auto()
    S_TPC = auto()
    S_DATA = auto()
    S_RDY = auto()
    S_DNC = auto()

    def name_as_id(self) -> str:
        return self.name.lower().replace("_", "-")


class ModeParameter(NamedTuple):
    delay_start: int
    delay_bs: int


class SymbolType(Enum):
    START = auto()
    TPC = auto()
    DATA = auto()
    RDY = auto()
    RDY_WAIT = auto()
    DELAY = auto()


@dataclass
class TransactionSymbol:
    samplenum: int
    shift: int
    type_: SymbolType

    def as_annotation_data(self) -> Optional[ClassAnnotationPair]:
        if self.type_ == SymbolType.START:
            return (Annotation.S_START, ["Start", "S"])
        elif self.type_ == SymbolType.TPC:
            return (Annotation.S_TPC, [f"{self.shift:1X}"])
        elif self.type_ == SymbolType.DATA:
            return (Annotation.S_DATA, [f"{self.shift:1X}"])
        elif self.type_ == SymbolType.RDY or self.type_ == SymbolType.RDY_WAIT:
            return (
                Annotation.S_RDY,
                ["RDY", "R"] if self.shift == 0 else ["!RDY", "!R", "!"],
            )
        elif self.type_ == SymbolType.DELAY:
            return (Annotation.S_DNC, ["Delay", "DNC", "X"])


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


T = TypeVar("T")


def tail(n: int, iterable: Iterable[T]) -> Iterable[T]:
    "Return an iterator over the last n items."
    # tail(3, 'ABCDEFG') → E F G
    return iter(deque(iterable, maxlen=n))


def format_annotations(inp: Sequence[Tuple[Annotation, str]]) -> NameDescList:
    return tuple((idx.name_as_id(), desc) for idx, desc in inp)


def crc16(data: memoryview) -> int:
    crc = 0

    for b in data:
        crc = ((crc << 8) ^ CRC_TAB[b ^ (crc >> 8)]) & 0xFFFF

    return crc


class Decoder(
    BottomDecoder[PacketType],
    HasOptions,
    HasChannels,
    HasOptionalChannels,
    HasAnnotations,
    HasAnnotationRows,
):
    api_version = 3
    id = "msif"
    name = "MSIF"
    longname = "Memory Stick Interface"
    desc = "Memory Stick Interface link layer protocol."
    license = "gplv3+"
    inputs = ["logic"]
    outputs = ["msif"]
    tags = ["Memory"]
    options = (
        {
            "id": "bus-width",
            "desc": "Bus width",
            "default": "auto",
            "values": ("auto", "1-bit", "4-bit"),
        },
    )
    # These must be in the exact same order as the IntEnum
    channels = (
        {**Channel.SDIO.to_idname(), "desc": "Data line 0"},
        {**Channel.SCLK.to_idname(), "desc": "Clock line"},
        {**Channel.BS.to_idname(), "desc": "Bus state"},
    )
    optional_channels = (
        {**Channel.DATA1.to_idname(), "desc": "Data line 1"},
        {**Channel.DATA2.to_idname(), "desc": "Data line 2"},
        {**Channel.DATA3.to_idname(), "desc": "Data line 3"},
    )
    annotations = format_annotations(
        [
            (Annotation.TPC, "Transfer Protocol Command"),
            (Annotation.DATA, "Data"),
            (Annotation.DATA_RDY, "Data Ready"),
            (Annotation.W_CRC, "CRC Error"),
            (Annotation.W_FORMAT, "Invalid Data Format"),
            (Annotation.S_START, "Start"),
            (Annotation.S_TPC, "TPC Symbol"),
            (Annotation.S_DATA, "Data Symbol"),
            (Annotation.S_RDY, "Ready"),
            (Annotation.S_DNC, "Do Not Care"),
        ]
    )
    annotation_rows = (
        (
            "symbols",
            "Symbols",
            (
                Annotation.S_START,
                Annotation.S_TPC,
                Annotation.S_DATA,
                Annotation.S_RDY,
                Annotation.S_DNC,
            ),
        ),
        (
            "fields",
            "Fields",
            (
                Annotation.TPC,
                Annotation.DATA,
                Annotation.DATA_RDY,
            ),
        ),
        (
            "warnings",
            "Warnings",
            (
                Annotation.W_CRC,
                Annotation.W_FORMAT,
            ),
        ),
    )

    SCLK_POSEDGE: ClassVar[ChannelCondition] = {Channel.SCLK: "r"}
    MODES: ClassVar[Dict[Literal[1, 4], ModeParameter]] = {
        1: ModeParameter(1, 1),
        4: ModeParameter(4, 2),
    }

    out_ann: AnnotationStream
    out_python: PythonStream

    bits: Literal[1, 4] = 1
    allow_mode_switch: bool = False
    mode_switch_reg: Optional[bytes] = None
    mode_switch_val: Optional[bytes] = None

    state: StateLiteral
    next_state: StateLiteral
    bs: int
    delay_counter: int
    txn_buffer: List[TransactionSymbol]
    _txn_is_out: Optional[bool]

    def __init__(self):
        super().__init__()
        self.reset()

    def start(self) -> None:
        self.out_ann = self.register(OUTPUT_ANN)
        self.out_python = self.register(OUTPUT_PYTHON)

        options: OptionMap = self.get_options()

        if options["bus-width"] == "auto":
            self.allow_mode_switch = True
        elif options["bus-width"] == "4-bit":
            self.bits = 4

    def handle_mode_switch(self, packet: Optional[TransactionPacket]) -> bool:
        if not self.allow_mode_switch or packet is None:
            return False

        if packet.tpc == 0b1000:
            self.mode_switch_reg = packet.data
            self.mode_switch_val = None
            return False

        if self.mode_switch_reg is not None and packet.tpc == 0b1011:
            self.mode_switch_val = packet.data

        if self.mode_switch_reg is None or self.mode_switch_val is None:
            self.mode_switch_reg = None
            self.mode_switch_val = None
            return False

        wbase, wsize = self.mode_switch_reg[2], self.mode_switch_reg[3]
        if wbase == 0 and wsize == 0:
            self.mode_switch_reg = None
            self.mode_switch_val = None
            return False
        wend = wbase + wsize
        if wbase <= 0x10 < wend:
            val_offset = 0x10 - wbase
            if val_offset >= len(self.mode_switch_val):
                self.mode_switch_reg = None
                self.mode_switch_val = None
                return False
            cfg = self.mode_switch_val[val_offset]
            # TODO: MS classic seems to expect 0x88 before switching to 20MHz 4-bit mode.
            if cfg == 0x88:
                print("Switch to 4-bit mode (classic)")
                self.bits = 4
            elif cfg & 0x80:
                print("Switch to 1-bit mode")
                self.bits = 1
            elif not cfg & 0x80:
                print("Switch to 4-bit mode (pro)")
                self.bits = 4
            else:
                print(f"Unknown cfg write {cfg}")
            self.mode_switch_reg = None
            self.mode_switch_val = None
            return True

        self.mode_switch_reg = None
        self.mode_switch_val = None
        return False

    def put_data(
        self,
        start: int,
        end: int,
        dir_: Literal["IN", "OUT"],
        data: Union[bytes, bytearray],
    ) -> Tuple[int, bool]:
        if len(data) < 3:
            self.put(
                start, end, self.out_ann, (Annotation.W_FORMAT, ["Data too short."])
            )
            return -1, False
        payload = memoryview(data)[:-2]
        crc_expected = (data[-2] << 8) | data[-1]
        crc_actual = crc16(payload)
        crc_ok = "OK" if crc_expected == crc_actual else "NG"

        with_hex = []
        payload_str = " ".join(f"{b:02X}" for b in payload)
        with_hex.append(f"{dir_} [ {payload_str} ] CRC: {crc_expected:04X} ({crc_ok})")
        for l in range(64, 7, -8):
            if len(payload) > l:
                payload_str_short = " ".join(f"{b:02X}" for b in payload[:l])
                with_hex.append(
                    f"{dir_} [ {payload_str_short} ... ] CRC: {crc_expected:04X} ({crc_ok})"
                )

        self.put(
            start,
            end,
            self.out_ann,
            (Annotation.DATA, [*with_hex, f"{dir_} CRC: {crc_ok}", dir_, dir_[0]]),
        )

        if crc_ok != "OK":
            self.put(
                start,
                end,
                self.out_ann,
                (
                    Annotation.W_CRC,
                    [f"CRC mismatch (exp.: {crc_expected:04X} got: {crc_actual:04X})"],
                ),
            )
            return crc_expected, False
        return crc_expected, True

    def decode(self, /) -> None:
        while True:
            latched = self.wait(self.SCLK_POSEDGE)
            if latched is None:
                return

            mode = self.MODES[self.bits]
            sdio, _, bs, data1, data2, data3 = latched
            bits = self.bits
            state = self.state
            shift = 0
            flip = self.txn_bs_flip(bs)

            if bits == 4 and (data1 == 0xff or data2 == 0xff or data3 == 0xff):
                raise RuntimeError('Decoder is in 4-bit mode but required inputs are not available.')

            if bits == 1:
                shift = sdio
            elif bits == 4:
                shift = (data3 << 3) | (data2 << 2) | (data1 << 1) | sdio

            symbol_type: Optional[SymbolType] = None
            if state == "IDLE" and bs == 1:
                symbol_type = SymbolType.START
                if flip:
                    self.txn_transition("TPC", mode.delay_start)
            elif state == "TPC":
                symbol_type = SymbolType.TPC
                if flip:
                    is_out = self.txn_is_out()
                    if is_out is None:
                        # TODO report error
                        self.txn_finish()
                        continue
                    elif is_out:
                        self.txn_transition("OUT_DATA", mode.delay_bs)
                    else:
                        self.txn_transition("IN_RDY", mode.delay_bs)
            elif state == "OUT_DATA":
                symbol_type = SymbolType.DATA
                if flip:
                    self.txn_transition("OUT_RDY", mode.delay_bs)
            elif state == "IN_RDY":
                symbol_type = SymbolType.RDY
                if flip:
                    self.txn_transition("IN_DATA", mode.delay_bs)
            elif state == "OUT_RDY":
                symbol_type = SymbolType.RDY
                if flip:
                    self.txn_transition("IDLE", mode.delay_bs)
            elif state == "IN_DATA":
                symbol_type = SymbolType.DATA
                if flip:
                    self.txn_transition("IDLE", mode.delay_bs)

            if symbol_type is None and bs == 0:
                continue

            assert symbol_type is not None

            self.txn_buffer.append(
                TransactionSymbol(self.samplenum, shift, symbol_type)
            )
            self.txn_handle_transition()

    def txn_finish(self):
        """
        Process the transaction buffer, pass it around and clear the
        transaction state.
        """
        self.txn_post_proc()
        packet = self.txn_annotate()
        self.handle_mode_switch(packet)
        self.txn_reset()

    def txn_post_proc(self):
        """
        Post-process the transaction buffer.

        This helper exists because it's a PITA to insert those specific delays
        using the state machine alone, and the code became unmanagable.
        """
        if self.bits == 4:
            # Only the first 2 symbols of the TPC are real
            for sym in islice(
                (s for s in self.txn_buffer if s.type_ == SymbolType.TPC), 2, None
            ):
                sym.type_ = SymbolType.DELAY
            # The last 2 data symbols of an out transaction are actually delays
            if self.txn_is_out():
                for sym in tail(
                    2, (s for s in self.txn_buffer if s.type_ == SymbolType.DATA)
                ):
                    sym.type_ = SymbolType.DELAY
        for sym in self.txn_buffer:
            if sym.type_ == SymbolType.RDY:
                if sym.shift & 1:
                    sym.type_ = SymbolType.RDY_WAIT
                else:
                    break

    def txn_annotate(self) -> Optional[TransactionPacket]:
        if len(self.txn_buffer) == 0:
            return None

        packet: Optional[TransactionPacket] = None

        timestamps = list(
            (sym0.samplenum, sym1.samplenum) for sym0, sym1 in pairwise(self.txn_buffer)
        )
        # Assume the last SCLK pulse is the same as the one that came before it.
        previous_pulse_duration = timestamps[-1][1] - timestamps[-1][0]
        last_timestamp = self.txn_buffer[-1].samplenum
        timestamps.append((last_timestamp, last_timestamp + previous_pulse_duration))

        txn_start = timestamps[0][0]
        txn_end = timestamps[-1][1]

        index = {
            k: list(v)
            for k, v in groupby(
                zip(timestamps, self.txn_buffer), key=lambda p: p[1].type_
            )
        }

        for (ss, es), sym in zip(timestamps, self.txn_buffer):
            ad = sym.as_annotation_data()
            if ad is not None:
                self.put(ss, es, self.out_ann, ad)

        if SymbolType.TPC not in index:
            self.put(
                txn_start,
                txn_end,
                self.out_ann,
                (Annotation.W_FORMAT, ["State machine error: Missing TPC field."]),
            )
            return None

        syms_tpc = index[SymbolType.TPC]
        tpcb = 0
        tpc_start = syms_tpc[0][0][0]
        tpc_end = syms_tpc[-1][0][1]
        if len(syms_tpc) * self.bits != 8:
            self.put(
                tpc_start,
                tpc_end,
                self.out_ann,
                (Annotation.W_FORMAT, ["TPC length is not 8-bit."]),
            )

        for _, sym in syms_tpc:
            tpcb <<= self.bits
            tpcb |= sym.shift

        tpc = tpcb >> 4

        if (tpcb >> 4) ^ (tpcb & 0b1111) != 0b1111:
            self.put(
                tpc_start,
                tpc_end,
                self.out_ann,
                (Annotation.W_FORMAT, ["Invalid TPC."]),
            )
        else:
            self.put(
                tpc_start,
                tpc_end,
                self.out_ann,
                (
                    Annotation.TPC,
                    [f"{TPC_NAMES.get(tpc, 'Unknown')} ({tpc:04b})", f"{tpc:04b}", "T"],
                ),
            )

        if SymbolType.DATA not in index:
            self.put(
                txn_start,
                txn_end,
                self.out_ann,
                (Annotation.W_FORMAT, ["State machine error: Missing DATA field."]),
            )
            return None

        syms_data = index[SymbolType.DATA]
        data_start = syms_data[0][0][0]
        data_end = syms_data[-1][0][1]
        data_size_bytes, align = divmod(len(syms_data), 8 // self.bits)
        if align == 0:
            data_shift = 0
            for _, sym in syms_data:
                data_shift <<= self.bits
                data_shift |= sym.shift
            data = data_shift.to_bytes(data_size_bytes, "big")
            crc, crc_ok = self.put_data(
                data_start, data_end, ("OUT" if self.txn_is_out() else "IN"), data
            )
            packet = TransactionPacket(tpc, data[:-2], crc, crc_ok)
            self.put(
                timestamps[0][0], timestamps[-1][1], self.out_python, ("txn", packet)
            )
        else:
            self.put(
                data_start,
                data_end,
                self.out_ann,
                (Annotation.W_FORMAT, ["Data is not byte-aligned."]),
            )

        if SymbolType.RDY not in index:
            self.put(
                txn_start,
                txn_end,
                self.out_ann,
                (Annotation.W_FORMAT, ["State machine error: Missing RDY field."]),
            )
            return None

        syms_rdy = index[SymbolType.RDY]
        rdy_start = syms_rdy[0][0][0]
        rdy_end = syms_rdy[-1][0][1]
        self.put(
            rdy_start,
            rdy_end,
            self.out_ann,
            (Annotation.DATA_RDY, ["ACK", "A"] if self.txn_is_out() else ["RDY", "R"]),
        )

        return packet

    def txn_transition(self, next_state: StateLiteral, cycles: int = 0) -> None:
        if next_state != self.next_state:
            self.delay_counter = max(cycles - 1, 0)
            self.next_state = next_state

    def txn_handle_transition(self):
        if self.delay_counter == 0:
            self.state = self.next_state
            if self.next_state == "IDLE":
                self.txn_finish()
        else:
            self.delay_counter -= 1

    def txn_transition_pending(self) -> bool:
        return self.state != self.next_state

    def txn_bs_flip(self, bs: int) -> bool:
        result = self.bs != bs
        self.bs = bs
        return result

    def txn_is_out(self) -> Optional[bool]:
        if self._txn_is_out is not None:
            return self._txn_is_out

        first_symbol = next(
            (s for s in self.txn_buffer if s.type_ == SymbolType.TPC), None
        )
        if first_symbol is None:
            return None

        assert self.bits in (1, 4)

        if self.bits == 1:
            self._txn_is_out = bool(first_symbol.shift)
        elif self.bits == 4:
            self._txn_is_out = bool(first_symbol.shift & 0x8)

        return self._txn_is_out

    def txn_reset(self):
        self.state = self.next_state = "IDLE"
        self.bs = 0
        self.delay_counter = 0
        self.txn_buffer = []
        self._txn_is_out = None

    def reset(self) -> None:
        self.bits = 1
        self.allow_mode_switch = False
        self.mode_switch_reg = b"\x00\x00\x00\x00"
        self.mode_switch_val = b""
        self.txn_reset()


if TYPE_CHECKING:
    from typing import reveal_type

    reveal_type(Decoder())
