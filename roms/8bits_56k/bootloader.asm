; ============================================================================
; Z80 SIO/0 Serial Bootloader (< 256 bytes, ROM @ 0000h-1FFFh)
; Clock: 3.6864 MHz -> 115200 baud (x32 mode), 8N1, Polled I/O
; ============================================================================

SIO_AD      EQU     00h             ; Channel A Data    (B/A=0, C/D=0)
SIO_BD      EQU     01h             ; Channel B Data    (B/A=1, C/D=0)
SIO_AC      EQU     02h             ; Channel A Control (B/A=0, C/D=1)
SIO_BC      EQU     03h             ; Channel B Control (B/A=1, C/D=1)
LOAD_BASE   EQU     4000h           ; Target RAM base address

            ORG     0000h

reset:
            di                      ; Disable CPU interrupts
            ld      sp, 0000h       ; Stack at top of RAM (FFFFh on first push)

            ; Reset Channel B and initialize Channel A (115200 8N1)
            ld      a, 18h          ; WR0: Channel Reset
            out     (SIO_BC), a     ; Reset Channel B so INT stays inactive

            ld      hl, sio_init
            ld      b, sio_init_end - sio_init
			ld		c, SIO_AC
            otir                    ; Write configuration sequence to Channel A

            ; Zero shadow registers D'E'H'L' for 32-bit 0xDEADBEEF shift window
            exx
            ld      hl, 0000h
            ld      d, h
            ld      e, l
            exx

            ; 1) Tx string: 0x10 + "/boot.bin"
            ld      hl, boot_str
            ld      b, boot_str_end - boot_str
tx_banner:
            ld      a, (hl)
            call    tx_byte
            inc     hl
            djnz    tx_banner

            ; 2) Rx 3 bytes: N (0000h..7FFFh, little-endian) + data byte
            ;    (Swap B and C below if host transmits N big-endian)
rx_packet:
            call    rx_byte         ; Byte 0: N low
            ld      b, a
            call    rx_byte         ; Byte 1: N high
            ld      c, a
            call    rx_byte         ; Byte 2: Data byte
            ld      d, a

            ; Store data byte at $2000 + N
            ld      l, b            ; HL = N
            ld      h, c
            set     7, h            ; HL = $2000 + N (since N <= 7FFFh)
            ld      (hl), d         ; Write byte to RAM

            ; 3) Tx the same 3-byte message back
            ld      a, b
            call    tx_byte
            ld      a, c
            call    tx_byte
            ld      a, d
            call    tx_byte

            ; 4a) Check termination: N == 7FFFh
            ld      a, b
            inc     a               ; FFh + 1 -> 00h (Z=1 if B == FFh)
            jr      nz, check_magic
            ld      a, c
            cp      7Fh             ; Z=1 if C == 7Fh
            jr      z, soft_reset

            ; 4b) Check termination: last 4 data bytes == 0xDEADBEEF
check_magic:
            ld      a, d
            exx
            ld      d, e            ; Shift 32-bit window D'E'H'L' left 8 bits
            ld      e, h
            ld      h, l
            ld      l, a            ; L' = newest data byte

            ld      a, d
            cp      0DEh
            jr      nz, magic_miss
            ld      a, e
            cp      0ADh
            jr      nz, magic_miss
            ld      a, h
            cp      0BEh
            jr      nz, magic_miss
            ld      a, l
            cp      0EFh
            jr      z, soft_reset
magic_miss:
            exx
            jr      rx_packet

            ; 5) Soft reset peripherals/CPU state and jump to $8000
soft_reset:
            di
            ld      a, 18h          ; Channel Reset command
            out     (SIO_AC), a     ; Reset SIO/0 Channel A
            out     (SIO_BC), a     ; Reset SIO/0 Channel B
            ld      sp, 0000h       ; Reset stack pointer
            jp      LOAD_BASE       ; Start executing payload at $8000

; ----------------------------------------------------------------------------
; Polled Serial Subroutines (Channel A)
; ----------------------------------------------------------------------------
rx_byte:
            in      a, (SIO_AC)     ; Read RR0
            rra                     ; Bit 0 (Rx Character Available) -> Carry
            jr      nc, rx_byte
            in      a, (SIO_AD)     ; Fetch byte from Rx FIFO
            ret

tx_byte:
            push    af
tx_wait:
            in      a, (SIO_AC)     ; Read RR0
            bit     2, a            ; Test Bit 2 (Tx Buffer Empty)
            jr      z, tx_wait
            pop     af
            out     (SIO_AD), a     ; Load byte into Tx buffer
            ret

; ----------------------------------------------------------------------------
; Configuration & Banner Data
; ----------------------------------------------------------------------------
sio_init:
            db      18h             ; WR0: Channel Reset
            db      04h, 84h        ; WR4: x32 clock, 1 stop bit, no parity
            db      03h, 0C1h       ; WR3: Rx 8-bit, Rx Enable
            db      05h, 0EAh       ; WR5: DTR, Tx 8-bit, Tx Enable, RTS
            db      01h, 00h        ; WR1: All interrupts disabled
sio_init_end:

boot_str:
            db      10h, "/boot.bin"
boot_str_end:
