; mx65_hello_7seg.s - the smallest program that proves the IO path (guide section 7):
; light LED0, show "0" on digit 0, then hold forever.  Start your own firmware
; by copying this file, systems/mx65_hello_7seg.toml, and the assemble command
; in firmware/README.md.
.setcpu "6502"

LED_LO   = $E020                ; LED bits 7..0
SEG_BASE = $E030                ; digit 0 segment register

.segment "CODE"
reset:
        sei                     ; no interrupts: we never leave the spin
        cld
        ldx     #$ff
        txs                     ; stack at $01FF (unused, but defined)
        lda     #$01
        sta     LED_LO          ; LED0 on
        lda     GLYPH0
        sta     SEG_BASE        ; digit 0 shows "0"
spin:   jmp     spin            ; hold the display

irq_handler:
        rti                     ; valid handler for stray IRQ/NMI/BRK

.segment "RODATA"
GLYPH0: .byte   $3F             ; active-high dp,g,f,e,d,c,b,a for "0"

.segment "VECTORS"
        .addr   irq_handler     ; $FFFA NMI
        .addr   reset           ; $FFFC RESET
        .addr   irq_handler     ; $FFFE IRQ / BRK
