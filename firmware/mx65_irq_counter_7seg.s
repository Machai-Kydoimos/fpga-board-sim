; ===========================================================================
; mx65_irq_counter_7seg.s - interrupt-driven walking counter (two sources)
;
; Same visible behavior as mx65_walking_counter_7seg.s, but driven by a small
; interrupt controller in cpu_io with TWO sources multiplexed onto the CPU's
; single (active-low) IRQ line:
;
;   * TIMER  (IFR bit0) - the prescaler tick; paces the animation.
;   * INPUT  (IFR bit1) - any sw/btn change (edge-detected in hardware); the
;                          user acted, so re-read the controls.
;
;   IER ($E011) enables sources; IFR ($E012) is the flag register (read to see
;   who fired; write-1-to-clear to acknowledge).  The main loop just enables
;   interrupts and idles; the ISR reads IFR and dispatches.
;
; The subroutines and glyph table are identical to the polled program.
; Assembled with ca65 + ld65.
; ===========================================================================

.setcpu "6502"

; --- Memory-mapped IO registers (must match the cpu_io decode in the VHDL) ---
SW       = $E000
BTN      = $E002
CFG_LEDS = $E004
CFG_SEGS = $E005
IER      = $E011                ; interrupt enable  (bit0 timer, bit1 input)
IFR      = $E012                ; interrupt flag    (read = status; write-1-to-clear)
LED_LO   = $E020
LED_HI   = $E021
SEG_BASE = $E030

SKIP_BASE = 8                   ; step divider at 0 switches (each switch halves it)

; --- Zero-page state --------------------------------------------------------
POS       = $00
FWD       = $01
CNT_UP    = $02
PREVBTN   = $03
CURBTN    = $04
LAMP      = $05
SKIP_VAL  = $06
SKIPCNT   = $07
N_LEDS    = $08
N_SEGS    = $09
ONEHOT_LO = $0A
ONEHOT_HI = $0B
TMPFLAGS  = $0C                 ; snapshot of IFR taken at ISR entry
BCD       = $10                 ; BCD[0..N_SEGS-1], one digit each; 0 = units

.segment "CODE"

; --- Cold start: set up state, enable interrupts, then idle -----------------
reset:
        sei
        cld
        ldx     #$ff
        txs

        lda     CFG_LEDS
        sta     N_LEDS
        lda     CFG_SEGS
        sta     N_SEGS

        lda     #0
        sta     POS
        sta     PREVBTN
        sta     LAMP
        ldx     #0
@zbcd:  sta     BCD,x
        inx
        cpx     #8
        bcc     @zbcd

        lda     #1
        sta     FWD
        sta     CNT_UP
        sta     SKIPCNT         ; first timer tick is a step
        jsr     calc_skip       ; initial step rate from the switches

        lda     #$03
        sta     IFR             ; clear any power-on flags (write-1-to-clear both)
        lda     #$03
        sta     IER             ; enable timer (bit0) + input-change (bit1)
        cli                     ; enable IRQ globally
@idle:  jmp     @idle           ; all work happens in the ISR

; --- Interrupt service routine: read IFR, dispatch, acknowledge -------------
irq:
        pha                     ; save A, X, Y
        txa
        pha
        tya
        pha

        lda     IFR             ; which source(s) fired?
        sta     TMPFLAGS

        and     #$01            ; timer?
        beq     @no_timer
        jsr     do_timer
        lda     #$01
        sta     IFR             ; ack timer (write-1-to-clear bit0)
@no_timer:
        lda     TMPFLAGS
        and     #$02            ; input change?
        beq     @no_input
        jsr     do_input
        lda     #$02
        sta     IFR             ; ack input (write-1-to-clear bit1)
@no_input:
        pla                     ; restore Y, X, A
        tay
        pla
        tax
        pla
        rti

; --- Timer source: advance the animation, then render -----------------------
do_timer:
        dec     SKIPCNT
        bne     @render         ; not a step tick: re-render current state
        lda     SKIP_VAL
        sta     SKIPCNT
        jsr     bounce
        lda     CNT_UP
        bne     @inc
        jsr     bcd_dec
        jmp     @render
@inc:
        jsr     bcd_inc
@render:
        jsr     render
        rts

; --- Input source: re-sample the controls on any sw/btn change --------------
do_input:
        lda     BTN
        and     #$01
        sta     CURBTN
        beq     @noedge
        lda     PREVBTN
        bne     @noedge
        lda     FWD             ; btn0 rising edge -> reverse both directions
        eor     #$01
        sta     FWD
        lda     CNT_UP
        eor     #$01
        sta     CNT_UP
@noedge:
        lda     CURBTN
        sta     PREVBTN
        lda     BTN             ; btn1 held -> lamp test (level)
        and     #$02
        sta     LAMP
        jsr     calc_skip       ; recompute step rate from the switches
        rts

; --- Render the current state to the LEDs and 7-seg digits -------------------
render:
        jsr     onehot
        lda     LAMP
        beq     @led_normal
        lda     #$ff
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
        lda     #$ff
        jmp     @seg_put
@seg_normal:
        ldy     BCD,x
        lda     DECLUT,y
@seg_put:
        sta     SEG_BASE,x
        inx
        jmp     @seg_loop
@seg_done:
        rts

; --- Subroutines (identical to the polled program) --------------------------

; Bounce POS within [0, N_LEDS-1], flipping FWD at each end.
bounce:
        lda     FWD
        beq     @back
        ldx     POS
        inx
        cpx     N_LEDS
        bcc     @store
        ldx     N_LEDS
        dex
        dex
        stx     POS
        lda     #0
        sta     FWD
        rts
@back:
        ldx     POS
        beq     @hit_bottom
        dex
        stx     POS
        rts
@hit_bottom:
        ldx     #1
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
        bcc     @done
        lda     #0
        sta     BCD,x
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
        sta     BCD,x
        inx
        cpx     N_SEGS
        bcc     @l
        rts
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
        ldx     #0
        ldy     #8
@pc:    lsr     a
        bcc     @nc
        inx
@nc:    dey
        bne     @pc
        lda     #SKIP_BASE
@sh:    cpx     #0
        beq     @done
        cmp     #1
        beq     @done
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
        .addr   nmi_stub        ; $FFFA NMI
        .addr   reset           ; $FFFC RESET
        .addr   irq             ; $FFFE IRQ / BRK

.segment "CODE"
nmi_stub:
        rti
