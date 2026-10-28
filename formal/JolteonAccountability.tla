--------------------------- MODULE JolteonAccountability ---------------------------
(***************************************************************************)
(* Accountable safety of Jolteon-style two-chain HotStuff with timeout      *)
(* certificates (TCs), bounded model (理论_可问责安全与纪元交接 §3.1 定理 1, *)
(* 命题 3). TLA+ port of formal/mc_jolteon.py; abstract model only.          *)
(*                                                                         *)
(* * Equal weights; a quorum is a set holding more than 2/3 of the nodes.   *)
(*   Byz holds more than 1/3, so forks are possible.                         *)
(* * Byzantine nodes are not processes: they sign anything at any time, so  *)
(*   a certificate is formable as soon as the honest signatures it needs    *)
(*   exist, and every leader is Byzantine (any valid block built from        *)
(*   formable certificates may be proposed at any time). Proposals are not  *)
(*   state; a vote picks a block constructible at that moment.              *)
(* * Block = <<v, parent, tc>>: justify QC = QC(parent), j = parent view < v *)
(*   (V1); if j < v-1 the block embeds TC(v-1) (V2), tc = <<m, q>>, m <= j   *)
(*   the largest reported hq and q a block with a QC at view m carried by    *)
(*   the TC. Genesis G has a QC everyone knows.                              *)
(* * Honest node k: h (highest certificate view known; k is in view h+1),   *)
(*   hq (block of its highest QC), ell (highest view it signed), voted and  *)
(*   timed-out views. A step first learns formable certificates, then signs *)
(*   (macro step: learning only matters for the next signature and           *)
(*   formability only grows, so postponing it loses no behaviour).          *)
(* * Commit (two-chain): X is committed with X+ when X+ has view(X)+1,      *)
(*   parent X, and both have formable QCs.                                   *)
(* Invariants: NoHonestE3 (lemma 1); Theorem1 (for every fork and every     *)
(* choice of signer sets, the case analysis A, B, C1, C2, C3 of the proof    *)
(* applies and its culprit set holds more than 1/3 and no honest node).      *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, TLC

CONSTANTS Honest,      \* honest nodes (model values)
          Byz,         \* Byzantine nodes (model values), more than 1/3 of all
          V,           \* largest view
          R3,          \* TRUE: signed views are monotone (no late votes)
          Adopting     \* TRUE: entering a view by a TC adopts the QC it carries

ASSUME Honest \cap Byz = {} /\ V \in Nat /\ R3 \in BOOLEAN /\ Adopting \in BOOLEAN

VARIABLES hs, votes, tmos
vars == <<hs, votes, tmos>>

Nodes == Honest \cup Byz
N == Cardinality(Nodes)
IsQuorum(S) == 3 * Cardinality(S) > 2 * N
MoreThanThird(S) == 3 * Cardinality(S) > N
Max(a, b) == IF a > b THEN a ELSE b
Min(a, b) == IF a < b THEN a ELSE b

G == <<0, "genesis", "none">>
MaxB(a, b) == IF b[1] > a[1] THEN b ELSE a          \* higher view wins; ties keep a (R6)

Voters(b) == {k \in Honest : <<k, b>> \in votes}
QCok(b) == b = G \/ IsQuorum(Voters(b) \cup Byz)
QCBlocks == {b \in {x[2] : x \in votes} \cup {G} : QCok(b)}
Low(v, m) == {k \in Honest : \E t \in tmos : t[1] = k /\ t[2] = v /\ t[3] <= m}
TCok(v, m) == 0 <= m /\ m < v /\ IsQuorum(Low(v, m) \cup Byz)

Constructible(v) ==
    LET qs == QCBlocks
        direct == {<<v, p, "none">> : p \in {q \in qs : q[1] = v - 1}}
        viaTC == {x \in {<<v, p, <<q[1], q>> >> : p \in qs, q \in qs} :
                     x[2][1] < v - 1 /\ x[3][1] <= x[2][1] /\ TCok(v - 1, x[3][1])}
    IN direct \cup viaTC

LearnOptions(k) ==
    LET s == hs[k]
        cands == {s.hq} \cup {b \in QCBlocks : b[1] > s.hq[1]}
    IN {o \in (0..V) \X cands :
          LET base == Max(s.h, o[2][1]) IN
          /\ o[1] >= base
          /\ \/ o[1] = base
             \/ \E q \in QCBlocks : TCok(o[1], q[1]) /\ (~Adopting \/ q[1] <= o[2][1])}

Init == /\ hs = [k \in Honest |-> [h |-> 0, hq |-> G, ell |-> 0, voted |-> {}, tmo |-> {}]]
        /\ votes = {}
        /\ tmos = {}

Timeout(k) ==
    \E o \in LearnOptions(k) :
        LET v == o[1] + 1 IN
        /\ v <= V
        /\ v \notin hs[k].tmo
        /\ hs' = [hs EXCEPT ![k] = [h |-> o[1], hq |-> o[2], ell |-> Max(hs[k].ell, v),
                                    voted |-> hs[k].voted, tmo |-> hs[k].tmo \cup {v}]]
        /\ tmos' = tmos \cup {<<k, v, o[2][1]>>}
        /\ UNCHANGED votes

Vote(k) ==
    \E o \in LearnOptions(k) :
        \E bv \in 1..Min(o[1] + 1, V) :
            /\ bv \notin hs[k].voted
            /\ bv \notin hs[k].tmo
            /\ (~R3 \/ bv > hs[k].ell)
            /\ \E b \in Constructible(bv) :
                 LET nhq0 == MaxB(o[2], b[2])
                     nhq == IF Adopting /\ b[3] # "none" THEN MaxB(nhq0, b[3][2]) ELSE nhq0
                 IN /\ hs' = [hs EXCEPT ![k] = [h |-> Max(o[1], bv - 1), hq |-> nhq,
                                                ell |-> Max(hs[k].ell, bv),
                                                voted |-> hs[k].voted \cup {bv}, tmo |-> hs[k].tmo]]
                    /\ votes' = votes \cup {<<k, b>>}
                    /\ UNCHANGED tmos

Next == \E k \in Honest : Timeout(k) \/ Vote(k)
Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(* Checks *)

\* Lemma 1 (soundness of E3): no honest node voted at view a for a block with justify view j and
\* later or at the same time timed out at a view >= a with hq < j.
NoHonestE3 == \A x \in votes : \A t \in tmos :
                  (t[1] = x[1] /\ t[2] >= x[2][1]) => t[3] >= x[2][2][1]

RECURSIVE Anc(_, _)
Anc(a, b) == IF b = a THEN TRUE ELSE IF b[1] = 0 THEN FALSE ELSE Anc(a, b[2])
Conflicting(x, y) == ~Anc(x, y) /\ ~Anc(y, x)

Commits == {c \in QCBlocks \X QCBlocks : c[2] # G /\ c[2][2] = c[1] /\ c[2][1] = c[1][1] + 1}
Q(b) == {S \in SUBSET (Voters(b) \cup Byz) : IsQuorum(S)}
GoodC(C) == C \cap Honest = {} /\ MoreThanThird(C)

RECURSIVE Zof(_, _)
Zof(b, u) == IF b[2][1] > u + 1 THEN Zof(b[2], u) ELSE b   \* ancestor with the smallest view above u+1

Judge(cx, cy) ==
    LET X == cx[1]
        Xp == cx[2]
        Y == cy[1]
        u == X[1]
        Z == Zof(Y, u)
        j == Z[2][1]
        w == Z[1]
        TCq == {S \in SUBSET (Low(w - 1, IF Z[3] = "none" THEN -1 ELSE Z[3][1]) \cup Byz) : IsQuorum(S)}
    IN
    IF Y[1] = u THEN \A q1 \in Q(X) : \A qy \in Q(Y) : GoodC(q1 \cap qy)                \* A, E1
    ELSE IF Y[1] = u + 1 THEN \A q2 \in Q(Xp) : \A qy \in Q(Y) : GoodC(q2 \cap qy)      \* B, E1
    ELSE /\ j < w
         /\ ~(u + 1 < j /\ j < w)
         /\ IF j = u + 1 THEN \A q2 \in Q(Xp) : \A qz \in Q(Z[2]) : GoodC(q2 \cap qz)    \* C1, E1
            ELSE IF j = u THEN \A q1 \in Q(X) : \A qz \in Q(Z[2]) : GoodC(q1 \cap qz)   \* C2, E1
            ELSE /\ Z[3] # "none"                                                         \* C3, E3
                 /\ Z[3][1] <= j
                 /\ \A q2 \in Q(Xp) : \A t \in TCq : GoodC(q2 \cap t)

Theorem1 == \A cx \in Commits : \A cy \in Commits :
                (Conflicting(cx[1], cy[1]) /\ cx[1][1] <= cy[1][1]) => Judge(cx, cy)

Symm == Permutations(Honest)
=============================================================================
