; ===========================================================================
; mx65_dice_7seg.s - firmware for the embedded-core LFSR/dice-roller demo
;
; Guide section 13 worked example: extends cpu_io with a peripheral (a
; free-running LFSR random-number register at $E008) instead of a new
; register file.
;
;   * cold start blanks every digit but 0, shows "0" on digit 0, LEDs off,
;   * each btn(0) rising edge reads the LFSR, reduces it to 1-6, and shows
;     that value on digit 0 (as a glyph) and LED_LO (as the raw binary
;     value),
;   * this system also has an UNEQUAL ROM/RAM map (see
;     systems/mx65_dice_7seg.toml) -- the runtime proof that Phase 2's
;     per-region address slices really are independent.
;
; A hardware prescaler raises a "tick" every 2^PRESCALER_BITS clocks; the CPU
; polls it (write-to-clear at TICK) so button sampling is decoupled from raw
; instruction speed -- same idiom as mx65_walking_counter_7seg.s.  Assembled
; with ca65 + ld65 (see README.md); the .bin is embedded as the VHDL ROM
; constant in hdl/mx65_dice_7seg.vhd.
; ===========================================================================

.setcpu "6502"

; --- Memory-mapped IO registers (must match the cpu_io decode in the VHDL) ---
BTN      = $E002                ; buttons, bits 7..0  (bit0 = btn0 = roll)
CFG_SEGS = $E005                ; config: NUM_SEGS
LFSR     = $E008                ; free-running LFSR random byte (peripheral)
TICK     = $E010                ; bit0 = tick pending; write any value to clear
LED_LO   = $E020                ; LED bits 7..0 -- binary readout of the roll
SEG_BASE = $E030                ; per-digit segment regs: $E030 + digit index

; --- Zero-page state --------------------------------------------------------
PREVBTN   = $00                 ; previous btn0 level (edge detect)
CURBTN    = $01                 ; current btn0 level
ROLL      = $02                 ; current die value, 1..6

.segment "CODE"

; --- Cold start -------------------------------------------------------------
reset:
        sei                     ; mask IRQ (we poll; no ISR)
        cld                     ; binary arithmetic
        ldx     #$ff
        txs                     ; stack pointer -> $01FF

        lda     #0
        sta     PREVBTN
        sta     LED_LO          ; LEDs off

        ldx     CFG_SEGS        ; blank every digit but 0 (digits 1..N_SEGS-1)
@zseg:  dex
        beq     @seg0
        lda     #0
        sta     SEG_BASE,x
        jmp     @zseg
@seg0:  lda     DECLUT          ; glyph for "0"
        sta     SEG_BASE
        ; fall through to main

; --- Main loop (one pass per prescaler tick) --------------------------------
main:
@wait:
        lda     TICK            ; bit0 set once per 2^PRESCALER_BITS clocks
        and     #$01
        beq     @wait           ; spin until a tick is pending
        sta     TICK            ; ack (a=1): a write clears the tick

        ; --- btn0 rising edge -> roll ----------------------------------
        lda     BTN
        and     #$01
        sta     CURBTN
        beq     @noedge         ; btn0 low now -> no rising edge
        lda     PREVBTN
        bne     @noedge         ; was already high -> still held, not an edge
        jsr     roll
@noedge:
        lda     CURBTN
        sta     PREVBTN
        jmp     main

; --- Subroutines ------------------------------------------------------------

; Read the LFSR, reduce mod 6, +1 -> 1..6; render to digit 0 and LED_LO.
roll:
        lda     LFSR
@modloop:
        cmp     #6
        bcc     @moddone        ; A < 6 (carry clear from CMP) -> done
        sbc     #6              ; A >= 6 (carry set from CMP) -> A -= 6
        jmp     @modloop
@moddone:
        clc
        adc     #1              ; A now 1..6
        sta     ROLL
        sta     LED_LO          ; binary readout
        tay
        lda     DECLUT,y        ; -> 7-seg glyph
        sta     SEG_BASE
        rts

; --- Decimal -> 7-seg glyph lookup (active-high dp,g,f,e,d,c,b,a) ------------
.segment "RODATA"
DECLUT:
        .byte   $3F, $06, $5B, $4F, $66     ; 0 1 2 3 4
        .byte   $6D, $7D, $07, $7F, $6F     ; 5 6 7 8 9

; --- CPU vectors ------------------------------------------------------------
.segment "VECTORS"
        .addr   irq_handler     ; $FFFA NMI
        .addr   reset           ; $FFFC RESET
        .addr   irq_handler     ; $FFFE IRQ / BRK

.segment "CODE"
irq_handler:
        rti
