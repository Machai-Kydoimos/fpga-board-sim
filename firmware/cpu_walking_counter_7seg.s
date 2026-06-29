; ===========================================================================
; cpu_walking_counter_7seg.s - firmware for the embedded-core 6502 system
;
; STAGE 1 (bring-up): light LED0 and show glyph '0' on every digit, then spin.
; Assembled with ca65 + ld65 (see README.md); the resulting .bin is embedded
; verbatim as the VHDL ROM constant in hdl/cpu_walking_counter_7seg.vhd.
;
; The walking-counter firmware replaces this program in Stage 2.
; ===========================================================================

.setcpu "6502"

; --- Memory-mapped IO registers (see the cpu_io address decode in the VHDL) --
LED_LO   = $E020                ; LED bits 7..0
CFG_SEGS = $E005                ; config register: NUM_SEGS (board digit count)
SEG_BASE = $E030                ; per-digit segment regs: $E030 + digit index
GLYPH_0  = $3F                  ; 7-seg pattern for '0' (active-high a..g, dp off)

.segment "CODE"

reset:
        sei                     ; mask IRQ (Stage 1 polls; no ISR yet)
        cld                     ; clear decimal mode -> defined arithmetic
        ldx     #$ff
        txs                     ; stack pointer -> $01FF

        lda     #$01
        sta     LED_LO          ; LED0 on

        lda     CFG_SEGS        ; A = NUM_SEGS, read from a config register
        tax                     ; X = digit count
        lda     #GLYPH_0
@digit:
        sta     SEG_BASE-1,x    ; write '0' to digit X-1 ($E030 .. $E030+N-1)
        dex
        bne     @digit          ; ...for every digit

spin:
        jmp     spin            ; hold the display

; IRQ / BRK / NMI handler: nothing to do (interrupts unused in Stage 1).
irq_handler:
        rti

.segment "VECTORS"
        .addr   irq_handler     ; $FFFA NMI
        .addr   reset           ; $FFFC RESET
        .addr   irq_handler     ; $FFFE IRQ / BRK
