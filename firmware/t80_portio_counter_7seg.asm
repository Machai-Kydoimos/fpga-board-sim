; ===========================================================================
; t80_portio_counter_7seg.asm - Z80 walking counter with PORT-MAPPED IO
;
; Same polled walking counter as firmware/t80_walking_counter_7seg.asm, but the
; IO registers live in the Z80's separate I/O space instead of the memory map:
; they are read/written with IN/OUT (which assert IORQ) rather than loads/stores.
; ROM and RAM stay in the memory space (MREQ).  The register file (cpu_io) and
; its offsets are unchanged -- only the transport differs:
;   SW $00  BTN $02  CFG_LEDS $04  CFG_SEGS $05  TICK $10
;   LED_LO $20  LED_HI $21  SEG_BASE $30 (per-digit, C-indexed OUT)
;
; The Z80 boots at $0000, so the program starts there; RAM variables live at
; $8000+.  Assembled with z88dk's z80asm (z80asm -b -o<bin>).
; ===========================================================================

        org 0

; --- IO ports (low byte of the old memory-mapped $E0xx addresses) -----------
        defc SW_PORT   = $00
        defc BTN_PORT  = $02
        defc CFGL_PORT = $04            ; NUM_LEDS
        defc CFGS_PORT = $05            ; NUM_SEGS
        defc TICK_PORT = $10            ; bit0 = tick pending; OUT to clear
        defc LEDL_PORT = $20
        defc LEDH_PORT = $21
        defc SEG_PORT  = $30            ; per-digit segment ports: $30 + digit
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
        defc BCD      = $8010            ; BCD[0..N_SEGS-1], one digit each; 0 = units

; --- Cold start -------------------------------------------------------------
reset:
        di                              ; polled; no interrupts
        ld sp, $8800                    ; stack at the top of RAM

        in a, (CFGL_PORT)
        ld (N_LEDS), a
        in a, (CFGS_PORT)
        ld (N_SEGS), a

        xor a
        ld (POS), a
        ld (PREVBTN), a
        ld hl, BCD                      ; zero the 8 possible BCD digits
        ld b, 8
zbcd:
        ld (hl), 0
        inc hl
        djnz zbcd

        ld a, 1
        ld (FWD), a
        ld (CNT_UP), a
        ld (SKIPCNT), a                 ; first tick is a step

; --- Main loop (one pass per prescaler tick) --------------------------------
main:
waittick:
        in a, (TICK_PORT)
        and 1
        jr z, waittick                  ; spin until a tick is pending
        out (TICK_PORT), a              ; ack (a = 1): an OUT clears the tick

        ; --- btn0 rising edge -> reverse LED walk and count direction -------
        in a, (BTN_PORT)
        and 1
        ld (CURBTN), a
        jr z, noedge                    ; btn0 low now
        ld a, (PREVBTN)
        or a
        jr nz, noedge                   ; was already high -> still held
        ld a, (FWD)
        xor 1
        ld (FWD), a
        ld a, (CNT_UP)
        xor 1
        ld (CNT_UP), a
noedge:
        ld a, (CURBTN)
        ld (PREVBTN), a

        ; --- btn1 (held) -> lamp-test flag ----------------------------------
        in a, (BTN_PORT)
        and 2
        ld (LAMP), a

        ; --- switch popcount -> step divider --------------------------------
        call calc_skip

        ; --- step only every SKIP_VAL-th tick -------------------------------
        ld a, (SKIPCNT)
        dec a
        ld (SKIPCNT), a
        jr nz, render
        ld a, (SKIP_VAL)
        ld (SKIPCNT), a
        call bounce
        ld a, (CNT_UP)
        or a
        jr nz, step_inc
        call bcd_dec
        jr render
step_inc:
        call bcd_inc

; --- render outputs ---------------------------------------------------------
render:
        call onehot
        ld a, (LAMP)
        or a
        jr z, led_normal
        ld a, $ff                       ; lamp test: all LEDs on
        out (LEDL_PORT), a
        out (LEDH_PORT), a
        jr do_segs
led_normal:
        ld a, (ONEHOT_LO)
        out (LEDL_PORT), a
        ld a, (ONEHOT_HI)
        out (LEDH_PORT), a

do_segs:
        ld c, SEG_PORT                  ; dest: segment ports (C-indexed OUT)
        ld de, BCD                      ; src: BCD digits (memory)
        ld a, (N_SEGS)
        ld b, a
seg_loop:
        ld a, (LAMP)
        or a
        jr z, seg_normal
        ld a, $ff                       ; lamp test: all segments on
        jr seg_put
seg_normal:
        ld a, (de)                      ; digit value 0-9
        push de                         ; save BCD pointer over the lookup
        ld hl, DECLUT                   ; glyph = DECLUT[digit]
        ld d, 0
        ld e, a
        add hl, de
        ld a, (hl)
        pop de
seg_put:
        out (c), a                      ; write glyph to segment port (C = $30+i)
        inc c
        inc de
        djnz seg_loop
        jp main

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
