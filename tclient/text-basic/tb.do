1 GOSUB 500
5 MAXFILES=2
10 OPEN "COM:88N1ENN" FOR INPUT AS 1
12 PRINT ">";
15 OPEN "COM:88N1ENN" FOR OUTPUT AS 2
20 I$="":R$="":W=0
25 ON COM GOSUB 300:COM ON
30 K$=INKEY$
32 IF W THEN GOSUB 400:GOTO 30
33 IF K$="" THEN 30
40 IF K$=CHR$(13) THEN GOSUB 100:GOTO 30
50 IF K$=CHR$(8) THEN IF LEN(I$)>0 THEN I$=LEFT$(I$,LEN(I$)-1):PRINT CHR$(8);" ";CHR$(8);
51 IF K$=CHR$(8) THEN 30
52 IF LEN(I$)<38 THEN I$=I$+K$:PRINT K$;
53 GOTO 30
100 IF I$="" THEN PRINT:PRINT ">";:RETURN
101 PRINT #2,I$:PRINT:I$="":W=1:D=0:T=0
102 PRINT "thinking";SPACE$(3);STRING$(3,8);
103 RETURN
200 IF W THEN PRINT STRING$(8,8);SPACE$(11);STRING$(11,8);:W=0 ELSE PRINT
205 PRINT TAB(40-LEN(R$));R$:R$="":PRINT ">";I$;:RETURN
300 C$=INPUT$(1,#1)
310 IF C$=CHR$(13) THEN GOSUB 200:RETURN
320 IF C$<>CHR$(10) AND LEN(R$)<39 THEN R$=R$+C$
330 RETURN
400 T=T+1:IF T<10 THEN RETURN
401 T=0:D=D MOD 3+1
402 IF W THEN PRINT STRING$(D,".");SPACE$(3-D);STRING$(3,8);
403 RETURN
500 CLS
510 PRINT "  OVERLORD TANDY       #                ";
520 PRINT "                      ##                ";
530 PRINT "                 #   # #                ";
540 PRINT "                # # #   #               ";
550 PRINT "               #   #    #               ";
560 PRINT "###########   #          #   ##########"
570 PRINT "          #  #            #  #          ";
580 PRINT "          #  #            # #           ";
590 PRINT "           ##              #            ";
600 PRINT
610 PRINT "Sam took all the RAM, 40kB is all u get ";
620 PRINT
630 S$=RIGHT$(TIME$,2):N=0
640 X$=RIGHT$(TIME$,2):IF X$=S$ THEN 640
650 S$=X$:N=N+1:IF N<2 THEN 640
660 CLS:PRINT "Overlord tandy is ready":PRINT
670 RETURN
