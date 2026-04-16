'''
This decoder sits on top of the 'msif' decoder and annotates high-level interactions between a Memory Stick host controller and a Memory Stick Pro / PS Vita memory card.

Recommended usage for generating a clear protocol dump through cli:

$ sigrok-cli -i ms.sr -P msif:bs=BS:sdio=SDIO:sclk=SCLK:data1=DATA1:data2=DATA2:data3:DATA3,mspro --protocol-decoder-ann-class -A msif='w-crc:w-format:w-glitch',msclassic='reg-io:get-int:data-io:w-length:w-seq'
'''

from .pd import Decoder
