----------------------------- MODULE MCHandover -----------------------------
(* The weight tables of the Handover_*.cfg models (a TLC configuration file cannot write a tuple). *)
EXTENDS Handover

\* Byzantine (node 2) 30% of both tables; the two honest nodes swap weights.
WA1 == <<37, 33, 30>>
WA2 == <<33, 37, 30>>
\* Four equal nodes (two Byzantine).
WEq == <<25, 25, 25, 25>>
\* Byzantine 35% of the old table, 28% of the new one.
WM1 == <<33, 32, 35>>
WM2 == <<38, 34, 28>>
=============================================================================
