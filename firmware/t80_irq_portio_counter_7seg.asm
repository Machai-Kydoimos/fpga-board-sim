; ===========================================================================
; t80_irq_portio_counter_7seg.asm - Z80 "realistic machine" walking counter:
;   interrupt mode 2 (vectored) + PORT-MAPPED IO together.
;
; This is the capstone that combines the two Z80 features:
;   * IM 2 vectored interrupts - an interrupt controller drives INT and puts a
;     per-source vector on the bus during INTA; the timer (vector $00) and the
;     sw/btn-change (vector $02) sources dispatch to separate ISRs via the CPU's
;     I:vector table at $0100.
;   * Port-mapped IO - the register file lives in the Z80 I/O space, reached with
;     IN/OUT (IORQ), not loads/stores.  ROM/RAM stay in the memory space (MREQ).
;
; In hardware M1_n keeps the two IORQ uses apart: INTA (M1_n low + IORQ) supplies
; the vector; IN/OUT (M1_n high + IORQ) select the register file.  The ISRs do not
; read IFR to dispatch -- the vector already chose the handler; each just does its
; work and acknowledges its source (OUT to the IFR port, write-1-to-clear).
;
;   Ports: SW $00  BTN $02  CFG_LEDS $04  CFG_SEGS $05  IER $11  IFR $12
;          LED_LO $20  LED_HI $21  SEG_BASE $30 (per-digit, C-indexed OUT)
;   I = $01 -> vector table at $0100 ($00 -> isr_timer, $02 -> isr_input).
;
; Assembled with z88dk's z80asm (z80asm -b -o<bin>).
; ===========================================================================

        org 0

; --- IO ports ---------------------------------------------------------------
        defc SW_PORT   = $00
        defc BTN_PORT  = $02
        defc CFGL_PORT = $04
        defc CFGS_PORT = $05
        defc IER_PORT  = $11            ; interrupt enable (bit0 timer, bit1 input)
        defc IFR_PORT  = $12            ; interrupt flag   (write-1-to-clear to ack)
        defc LEDL_PORT = $20
        defc LEDH_PORT = $21
        defc SEG_PORT  = $30
        defc SKIP_BASE = 8

; --- RAM variables (memory space, RAM region at $8000) ----------------------
        defc POS      = $8000
        defc FWD      = $8001
        defc CNT_UP   = $8002
        defc PREVBTN  = $8003
        defc CURBTN   = $8004
        defc LAMP     = $8005
        defc SKIP_VAL = $8006
        defc SKIPCNT  = $8007
        defc N_LEDS   = $8008
        defc N_SEGS   = $8009
        defc ONEHOT_LO = $800A
        defc ONEHOT_HI = $800B
        defc BCD      = $8010

        jp start                        ; $0000: boot -> main setup
        defs 0x100 - ASMPC, 0           ; pad to the page-aligned IM 2 vector table

; --- IM 2 vector table ($0100, I = $01): one ISR address per source ---------
vectable:
        defw isr_timer                  ; $0100: vector $00 (timer)
        defw isr_input                  ; $0102: vector $02 (input change)

; --- Cold start: set up state, arm IM 2, enable interrupts, idle ------------
start:
        di
        ld sp, $8800

        in a, (CFGL_PORT)
        ld (N_LEDS), a
        in a, (CFGS_PORT)
        ld (N_SEGS), a

        xor a
        ld (POS), a
        ld (PREVBTN), a
        ld (LAMP), a
        ld hl, BCD                      ; zero the 8 possible BCD digits
        ld b, 8
zbcd:
        ld (hl), 0
        inc hl
        djnz zbcd

        ld a, 1
        ld (FWD), a
        ld (CNT_UP), a
        ld (SKIPCNT), a                 ; first timer tick is a step
        call calc_skip                  ; initial step rate from the switches

        ld a, 3
        out (IFR_PORT), a               ; clear any power-on flags (write-1-to-clear)
        ld a, 3
        out (IER_PORT), a               ; enable timer (bit0) + input-change (bit1)
        ld a, 0x01
        ld i, a                         ; I = $01 -> vector table page ($0100)
        im 2
        ei
idle:
        jr idle                         ; all work happens in the ISRs

; --- Timer ISR (vector $00): advance the animation, then render -------------
isr_timer:
        push af
        push bc
        push de
        push hl
        call do_timer
        ld a, 1
        out (IFR_PORT), a               ; ack timer (write-1-to-clear bit0)
        pop hl
        pop de
        pop bc
        pop af
        ei
        reti

; --- Input ISR (vector $02): re-sample the controls on any sw/btn change ----
isr_input:
        push af
        push bc
        push de
        push hl
        call do_input
        ld a, 2
        out (IFR_PORT), a               ; ack input (write-1-to-clear bit1)
        pop hl
        pop de
        pop bc
        pop af
        ei
        reti

; --- Timer work: step every SKIP_VAL-th tick, then render -------------------
do_timer:
        ld a, (SKIPCNT)
        dec a
        ld (SKIPCNT), a
        jr nz, dt_render
        ld a, (SKIP_VAL)
        ld (SKIPCNT), a
        call bounce
        ld a, (CNT_UP)
        or a
        jr nz, dt_inc
        call bcd_dec
        jr dt_render
dt_inc:
        call bcd_inc
dt_render:
        call render
        ret

; --- Input work: btn0 rising edge reverses; btn1 held is a lamp test --------
do_input:
        in a, (BTN_PORT)
        and 1
        ld (CURBTN), a
        jr z, di_noedge
        ld a, (PREVBTN)
        or a
        jr nz, di_noedge
        ld a, (FWD)                     ; btn0 rising edge -> reverse both directions
        xor 1
        ld (FWD), a
        ld a, (CNT_UP)
        xor 1
        ld (CNT_UP), a
di_noedge:
        ld a, (CURBTN)
        ld (PREVBTN), a
        in a, (BTN_PORT)                ; btn1 held -> lamp test (level)
        and 2
        ld (LAMP), a
        call calc_skip                  ; recompute step rate from the switches
        ret

; --- Render current state to LEDs + 7-seg ----------------------------------
render:
        call onehot
        ld a, (LAMP)
        or a
        jr z, r_led_normal
        ld a, $ff                       ; lamp test: all LEDs on
        out (LEDL_PORT), a
        out (LEDH_PORT), a
        jr r_segs
r_led_normal:
        ld a, (ONEHOT_LO)
        out (LEDL_PORT), a
        ld a, (ONEHOT_HI)
        out (LEDH_PORT), a
r_segs:
        ld c, SEG_PORT                  ; dest: segment ports (C-indexed OUT)
        ld de, BCD                      ; src: BCD digits (memory)
        ld a, (N_SEGS)
        ld b, a
r_seg_loop:
        ld a, (LAMP)
        or a
        jr z, r_seg_normal
        ld a, $ff                       ; lamp test: all segments on
        jr r_seg_put
r_seg_normal:
        ld a, (de)                      ; digit value 0-9
        push de                         ; save BCD pointer over the lookup
        ld hl, DECLUT                   ; glyph = DECLUT[digit]
        ld d, 0
        ld e, a
        add hl, de
        ld a, (hl)
        pop de
r_seg_put:
        out (c), a                      ; write glyph to segment port (C = $30+i)
        inc c
        inc de
        djnz r_seg_loop
        ret

; --- Subroutines ------------------------------------------------------------

; Bounce POS within [0, N_LEDS-1], flipping FWD at each end.
bounce:
        ld a, (FWD)
        or a
        jr z, bounce_back
        ld a, (POS)                     ; forward
        inc a
        ld b, a                         ; b = POS+1
        ld a, (N_LEDS)
        cp b                            ; N_LEDS - (POS+1)
        jr z, bounce_top                ; POS+1 == N_LEDS -> hit top
        jr c, bounce_top                ; (defensive) POS+1 > N_LEDS
        ld a, b
        ld (POS), a
        ret
bounce_top:
        xor a                           ; FWD = 0, POS = N_LEDS-2
        ld (FWD), a
        ld a, (N_LEDS)
        dec a
        dec a
        ld (POS), a
        ret
bounce_back:
        ld a, (POS)
        or a
        jr z, bounce_bottom
        dec a
        ld (POS), a
        ret
bounce_bottom:
        ld a, 1                         ; FWD = 1, POS = 1
        ld (FWD), a
        ld (POS), a
        ret

; BCD increment with carry ripple across N_SEGS digits (wraps at all-9s).
bcd_inc:
        ld hl, BCD
        ld a, (N_SEGS)
        ld b, a
bi_loop:
        ld a, (hl)
        inc a
        cp 10
        jr c, bi_store                  ; digit < 10 -> no carry
        ld (hl), 0                      ; 10 -> 0, carry into next digit
        inc hl
        djnz bi_loop
        ret
bi_store:
        ld (hl), a
        ret

; BCD decrement with borrow ripple across N_SEGS digits (wraps at all-0s).
bcd_dec:
        ld hl, BCD
        ld a, (N_SEGS)
        ld b, a
bd_loop:
        ld a, (hl)
        or a
        jr nz, bd_dec                   ; digit != 0 -> decrement
        ld (hl), 9                      ; 0 -> 9, borrow from next digit
        inc hl
        djnz bd_loop
        ret
bd_dec:
        dec a
        ld (hl), a
        ret

; ONEHOT_LO/HI = 1 << POS  (POS in 0..15).
onehot:
        xor a
        ld (ONEHOT_HI), a
        ld a, 1
        ld (ONEHOT_LO), a
        ld a, (POS)
        or a
        ret z
        ld b, a
oh_shift:
        ld a, (ONEHOT_LO)
        add a, a                        ; shift left, bit7 -> carry
        ld (ONEHOT_LO), a
        ld a, (ONEHOT_HI)
        adc a, a                        ; carry -> bit0 of high byte
        ld (ONEHOT_HI), a
        djnz oh_shift
        ret

; SKIP_VAL = max(1, SKIP_BASE >> popcount(SW[7:0])); more switches -> faster.
calc_skip:
        in a, (SW_PORT)
        ld c, 0                         ; popcount
        ld b, 8
cs_pc:
        srl a
        jr nc, cs_nc
        inc c
cs_nc:
        djnz cs_pc
        ld a, SKIP_BASE
        ld b, c                         ; b = popcount (loop count)
        inc b
        dec b
        jr z, cs_done                   ; popcount 0 -> no halving
cs_sh:
        cp 1
        jr z, cs_done                   ; already at the floor
        srl a
        djnz cs_sh
cs_done:
        ld (SKIP_VAL), a
        ret

; --- Decimal -> 7-seg glyph lookup (active-high dp,g,f,e,d,c,b,a) ------------
DECLUT:
        defb $3F, $06, $5B, $4F, $66    ; 0 1 2 3 4
        defb $6D, $7D, $07, $7F, $6F    ; 5 6 7 8 9
