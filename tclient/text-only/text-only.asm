; Tandy 200 serial chat - 8085
; Type text + ENTER -> sent over RS-232 (9600 8N1)
; Received lines are shown right-aligned.
;
; !! ROM entry points below must be verified against the T200 ROM map !!
; (values shown are the Model 100 ones as I recall them; T200 differs)
        CPU  8085
        ORG  0EEB0h             ; = HIMEM 61104

LCD     EQU  503Ch              ; print char in A to screen     (VERIFY)
KYREAD  EQU  8B03h              ; poll keyboard: A=key, Z=none  (VERIFY)
SD232   EQU  8643h              ; send A out RS-232             (VERIFY)
RV232   EQU  8519h              ; recv RS-232: A=char, Z=none   (VERIFY)
SETSER  EQU  191Dh              ; init UART, HL -> STAT string  (FILL IN)

WIDTH   EQU  39                 ; usable columns (40 minus 1 to avoid wrap)
CR      EQU  0Dh
LF      EQU  0Ah
BS      EQU  08h

START:  LXI  SP,STACK
        LXI  H,COMSTR           ; "88N1E" = 9600 baud, 8 bits, no parity
        CALL SETSER
        XRA  A
        STA  ILEN
        STA  RLEN

; ---------------- main loop ----------------
LOOP:   CALL KYREAD
        JZ   CHKRX
        CPI  CR
        JZ   SEND
        CPI  BS
        JZ   BKSP
        MOV  B,A                ; store typed char in IBUF
        LDA  ILEN
        CPI  WIDTH
        JNC  CHKRX              ; line full
        MOV  E,A
        MVI  D,0
        LXI  H,IBUF
        DAD  D
        MOV  M,B
        INR  A
        STA  ILEN
        MOV  A,B
        CALL LCD                ; echo
        JMP  LOOP

BKSP:   LDA  ILEN
        ORA  A
        JZ   LOOP
        DCR  A
        STA  ILEN
        MVI  A,BS
        CALL LCD
        MVI  A,' '
        CALL LCD
        MVI  A,BS
        CALL LCD
        JMP  LOOP

; ---------------- transmit input line ----------------
SEND:   LXI  H,IBUF
        SHLD PTR
        LDA  ILEN
        STA  CNT
SLOOP:  LDA  CNT
        ORA  A
        JZ   SDONE
        DCR  A
        STA  CNT
        LHLD PTR
        MOV  A,M
        INX  H
        SHLD PTR
        CALL SD232
        JMP  SLOOP
SDONE:  MVI  A,CR
        CALL SD232
        MVI  A,LF
        CALL SD232
        XRA  A
        STA  ILEN
        MVI  A,CR               ; move local cursor to next line
        CALL LCD
        MVI  A,LF
        CALL LCD
        JMP  LOOP

; ---------------- receive ----------------
CHKRX:  CALL RV232
        JZ   LOOP
        CPI  CR
        JZ   SHOWRX
        CPI  LF
        JZ   LOOP
        MOV  B,A
        LDA  RLEN
        CPI  WIDTH
        JNC  LOOP               ; drop overflow
        MOV  E,A
        MVI  D,0
        LXI  H,RBUF
        DAD  D
        MOV  M,B
        INR  A
        STA  RLEN
        JMP  LOOP

; print RBUF right-aligned, then restore the in-progress input line
SHOWRX: MVI  A,CR
        CALL LCD
        LDA  RLEN
        MOV  B,A
        MVI  A,WIDTH
        SUB  B
        STA  CNT                ; pad = WIDTH - RLEN
PAD:    LDA  CNT
        ORA  A
        JZ   PTXT
        DCR  A
        STA  CNT
        MVI  A,' '
        CALL LCD
        JMP  PAD
PTXT:   LXI  H,RBUF
        SHLD PTR
        LDA  RLEN
        STA  CNT
        CALL PRINTN
        MVI  A,CR
        CALL LCD
        MVI  A,LF
        CALL LCD
        XRA  A
        STA  RLEN
        LXI  H,IBUF             ; redraw what the user was typing
        SHLD PTR
        LDA  ILEN
        STA  CNT
        CALL PRINTN
        JMP  LOOP

; print CNT chars starting at (PTR) to screen
PRINTN: LDA  CNT
        ORA  A
        RZ
        DCR  A
        STA  CNT
        LHLD PTR
        MOV  A,M
        INX  H
        SHLD PTR
        CALL LCD
        JMP  PRINTN

; ---------------- data ----------------
COMSTR: DB   '88N1ENN'
ILEN:   DB   0
RLEN:   DB   0
CNT:    DB   0
PTR:    DW   0
IBUF:   DS   40
RBUF:   DS   40
        DS   64
STACK   EQU  $
