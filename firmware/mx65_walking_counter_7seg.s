; ===========================================================================
; mx65_walking_counter_7seg.s - firmware for the embedded-core 6502 system
;
; Replicates hdl/walking_counter_7seg.vhd in software:
;   * a single lit LED bounces back and forth across all LEDs (Knight Rider),
;   * every LED step advances a decimal odometer on the 7-segment digits,
;   * btn(0) (rising edge) reverses the LED walk AND the count direction,
;   * btn(1) (held) lights every LED and every segment (lamp test),
;   * each active switch doubles the step rate (a chosen 2x approximation; the
;     reference RTL's own comments say "doubles" though its code quadruples).
;
; A hardware prescaler raises a "tick" every 2^PRESCALER_BITS clocks; the CPU
; polls it (write-to-clear at TICK) so the visible rate is decoupled from raw
; instruction speed.  Assembled with ca65 + ld65 (see README.md); the .bin is
; embedded as the VHDL ROM constant in hdl/mx65_walking_counter_7seg.vhd.
; ===========================================================================

.setcpu "6502"

; --- Memory-mapped IO registers (must match the cpu_io decode in the VHDL) ---
SW       = $E000                ; switches, bits 7..0
BTN      = $E002                ; buttons, bits 7..0  (bit0 = btn0, bit1 = btn1)
CFG_LEDS = $E004                ; config: NUM_LEDS
CFG_SEGS = $E005                ; config: NUM_SEGS
TICK     = $E010                ; bit0 = tick pending; write any value to clear
LED_LO   = $E020                ; LED bits 7..0
LED_HI   = $E021                ; LED bits 15..8
SEG_BASE = $E030                ; per-digit segment regs: $E030 + digit index

SKIP_BASE = 8                   ; step divider at 0 switches (each switch halves it)

; --- Zero-page state --------------------------------------------------------
POS       = $00                 ; lit LED index (0 .. N_LEDS-1)
FWD       = $01                 ; LED walk direction: 1 = toward higher index
CNT_UP    = $02                 ; counter direction: 1 = increment
PREVBTN   = $03                 ; previous btn0 level (edge detect)
CURBTN    = $04                 ; current btn0 level
LAMP      = $05                 ; nonzero while btn1 held (lamp test)
SKIP_VAL  = $06                 ; ticks per step (1 = every tick)
SKIPCNT   = $07                 ; down-counter to the next step
N_LEDS    = $08                 ; cached NUM_LEDS
N_SEGS    = $09                 ; cached NUM_SEGS
ONEHOT_LO = $0A                 ; 1 << POS, low byte
ONEHOT_HI = $0B                 ; 1 << POS, high byte
BCD       = $10                 ; BCD[0..N_SEGS-1], one digit (0-9) each; 0 = units

.segment "CODE"

; --- Cold start -------------------------------------------------------------
reset:
        sei                     ; mask IRQ (we poll; no ISR)
        cld                     ; binary arithmetic
        ldx     #$ff
        txs                     ; stack pointer -> $01FF

        lda     CFG_LEDS
        sta     N_LEDS
        lda     CFG_SEGS
        sta     N_SEGS

        lda     #0
        sta     POS
        sta     PREVBTN
        ldx     #0              ; zero all 8 possible BCD digits
@zbcd:  sta     BCD,x
        inx
        cpx     #8
        bcc     @zbcd

        lda     #1
        sta     FWD             ; start walking up
        sta     CNT_UP          ; start counting up
        sta     SKIPCNT         ; first tick is a step
        ; fall through to main

; --- Main loop (one pass per prescaler tick) --------------------------------
main:
@wait:
        lda     TICK            ; bit0 set once per 2^PRESCALER_BITS clocks
        and     #$01
        beq     @wait           ; spin until a tick is pending
        sta     TICK            ; ack (a=1): a write clears the tick

        ; --- btn0 rising edge -> reverse LED walk and count direction -------
        lda     BTN
        and     #$01
        sta     CURBTN
        beq     @noedge         ; btn0 low now -> no rising edge
        lda     PREVBTN
        bne     @noedge         ; was already high -> still held, not an edge
        lda     FWD
        eor     #$01
        sta     FWD
        lda     CNT_UP
        eor     #$01
        sta     CNT_UP
@noedge:
        lda     CURBTN
        sta     PREVBTN

        ; --- btn1 (held) -> lamp-test flag ----------------------------------
        lda     BTN
        and     #$02
        sta     LAMP

        ; --- switch popcount -> step divider --------------------------------
        jsr     calc_skip

        ; --- step only every SKIP_VAL-th tick -------------------------------
        dec     SKIPCNT
        bne     render          ; not a step tick: just re-render current state
        lda     SKIP_VAL
        sta     SKIPCNT
        jsr     bounce          ; advance the LED position (bounce at the ends)
        lda     CNT_UP
        bne     @inc
        jsr     bcd_dec
        jmp     render
@inc:
        jsr     bcd_inc

        ; --- render outputs -------------------------------------------------
render:
        jsr     onehot          ; ONEHOT_LO/HI = 1 << POS

        lda     LAMP
        beq     @led_normal
        lda     #$ff            ; lamp test: all LEDs on
        sta     LED_LO
        sta     LED_HI
        jmp     @segs
@led_normal:
        lda     ONEHOT_LO
        sta     LED_LO
        lda     ONEHOT_HI
        sta     LED_HI

@segs:
        ldx     #0
@seg_loop:
        cpx     N_SEGS
        bcs     @seg_done
        lda     LAMP
        beq     @seg_normal
        lda     #$ff            ; lamp test: all segments on
        jmp     @seg_put
@seg_normal:
        ldy     BCD,x           ; digit value 0-9
        lda     DECLUT,y        ; -> 7-seg glyph
@seg_put:
        sta     SEG_BASE,x
        inx
        jmp     @seg_loop
@seg_done:
        jmp     main

; --- Subroutines ------------------------------------------------------------

; Bounce POS within [0, N_LEDS-1], flipping FWD at each end.
bounce:
        lda     FWD
        beq     @back
        ldx     POS
        inx
        cpx     N_LEDS
        bcc     @store          ; POS+1 < N_LEDS -> step up
        ldx     N_LEDS          ; hit the top: reverse, step back down
        dex
        dex                     ; X = N_LEDS-2
        stx     POS
        lda     #0
        sta     FWD
        rts
@back:
        ldx     POS
        beq     @hit_bottom
        dex                     ; step down
        stx     POS
        rts
@hit_bottom:
        ldx     #1              ; hit the bottom: reverse, step back up
        stx     POS
        lda     #1
        sta     FWD
@store:
        stx     POS
        rts

; BCD increment with carry ripple across N_SEGS digits (wraps at all-9s).
bcd_inc:
        ldx     #0
@l:     inc     BCD,x
        lda     BCD,x
        cmp     #10
        bcc     @done           ; digit < 10 -> no carry
        lda     #0
        sta     BCD,x           ; 10 -> 0, carry into next digit
        inx
        cpx     N_SEGS
        bcc     @l
@done:  rts

; BCD decrement with borrow ripple across N_SEGS digits (wraps at all-0s).
bcd_dec:
        ldx     #0
@l:     lda     BCD,x
        bne     @noborrow
        lda     #9
        sta     BCD,x           ; 0 -> 9, borrow from next digit
        inx
        cpx     N_SEGS
        bcc     @l
        rts                     ; borrow out of the top digit: wrapped to all 9s
@noborrow:
        dec     BCD,x
        rts

; ONEHOT_LO/HI = 1 << POS  (POS in 0..15).
onehot:
        lda     #0
        sta     ONEHOT_HI
        lda     #1
        sta     ONEHOT_LO
        ldx     POS
        beq     @done
@shift: asl     ONEHOT_LO
        rol     ONEHOT_HI
        dex
        bne     @shift
@done:  rts

; SKIP_VAL = max(1, SKIP_BASE >> popcount(SW[7:0])); more switches -> faster.
calc_skip:
        lda     SW
        ldx     #0              ; popcount accumulator
        ldy     #8              ; bit counter
@pc:    lsr     a
        bcc     @nc
        inx
@nc:    dey
        bne     @pc
        lda     #SKIP_BASE
@sh:    cpx     #0
        beq     @done           ; no more halving
        cmp     #1
        beq     @done           ; already at the floor
        lsr     a
        dex
        jmp     @sh
@done:  sta     SKIP_VAL
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
