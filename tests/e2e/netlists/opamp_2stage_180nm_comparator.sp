*=============================================================
*  CMOS Two-Stage Opamp Comparator (180nm) - E2E Test Netlist
*=============================================================
*  Technology : 180 nm CMOS (typical 1.8 V)
*  Architecture: Differential Input Pair + Active Load
*                Second Stage Common Source + Miller Compensation
*  Usage      : Subcircuit-wrapped for mixed-signal co-simulation
*               with D2A/A2D bridges via ngspice lazy-sync (bg_run)
*=============================================================

*------------ Subcircuit Definition ------------
.subckt opamp_2stage_180nm VDD VSS VINP VINN VOUT VBIAS

*------------ Differential Pair Stage ------------
* NMOS Input Pair
M1 N1 VINP NTAIL VSS NMOS L=0.18u W=9u
M2 N2 VINN NTAIL VSS NMOS L=0.18u W=9u

* PMOS Active Load (current mirror)
M3 N1 N1 VDD VDD PMOS L=0.18u W=18u   ; diode-connected load
M4 N2 N1 VDD VDD PMOS L=0.18u W=18u   ; active mirror load

*------------ Second Stage ------------
* Common-Source Amplifier (PMOS input)
M6 VOUT N2 VDD VDD PMOS L=0.18u W=72u

* Active NMOS Load
M5 VOUT VBIAS VSS VSS NMOS L=0.36u W=12u

*------------ Compensation ------------
* Miller R + C between Stage 1 output (N2) and Stage 2 output (VOUT)
Rcomp N2 N2C 1.5k
Ccomp N2C VOUT 2p

*------------ Tail Current Source ------------
* NMOS tail current transistor
M7 NTAIL VBIAS VSS VSS NMOS L=0.36u W=6u

*------------ Bias Circuit ------------
M8 VBIAS VBIAS VSS VSS NMOS L=0.36u W=6u

*------------ Load (convergence) ------------
RLOAD VOUT VSS 1Meg

.ends opamp_2stage_180nm

*------------ Device Models ------------
.model NMOS NMOS (LEVEL=1 VTO=0.7 KP=200u LAMBDA=0.02)
.model PMOS PMOS (LEVEL=1 VTO=-0.9 KP=100u LAMBDA=0.02)

*=============================================================
*  Testbench Wrapper
*=============================================================
*  DC supplies and external voltage sources for D2A/A2D bridges.
*  VSRCs with "external" keyword are controllable via ngspice
*  shared-library API (alter voltages at runtime during bg_run).
*=============================================================

*------------ Power Supplies ------------
V_VDD VDD 0 DC 1.8
V_VSS VSS 0 DC 0

*------------ Bias Supply ------------
V_BIAS VBIAS 0 DC 0.9

*------------ Input Sources (D2A-controllable) ------------
* VINN: inverting input - reference voltage for comparator
V_INN VINN 0 DC 0 external

* VINP: non-inverting input - signal input for comparator
V_INP VINP 0 DC 0 external

*------------ DUT Instance ------------
X1 VDD VSS VINP VINN VOUT VBIAS opamp_2stage_180nm

.end
