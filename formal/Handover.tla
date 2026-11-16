------------------------------- MODULE Handover -------------------------------
(***************************************************************************)
(* The epoch handover of Trust 2.0 with two weight tables, bounded model.  *)
(* TLA+ port of formal/mc_handover.py (which builds on mc_jolteon.py and   *)
(* JolteonAccountability.tla); abstract model only. Review S16, DESIGN.md  *)
(* 15.34.                                                                   *)
(*                                                                         *)
(* * Two epochs. The genesis block G (view 0) is the terminal block of     *)
(*   epoch 1 and its QC is known, so every other block of epoch 1 is a     *)
(*   suffix block and every view from 1 on is past the end of epoch 1.     *)
(*   Epoch 2 does not end within the bound.                                 *)
(* * Nodes are 0 .. n-1; W1 and W2 are the weights of the old and the new  *)
(*   table, as tuples (node k has W[k+1]). A quorum of a table holds more  *)
(*   than 2/3 of it.                                                        *)
(* * Block = <<v, parent, tc, epoch>>, tc = "none" or <<m, q, te>>: TC(v-1)*)
(*   of epoch te whose largest reported hq is m, carrying the QC of block  *)
(*   q of view m. A block of epoch 1 has a parent of epoch 1.              *)
(* * An honest node is in epoch 1 until it holds a commit proof of G: two  *)
(*   blocks of epoch 1 at adjacent views, parent and child, both certified *)
(*   (H3). Entering is part of learning, before a signature; the node then *)
(*   knows the QC of the child. In epoch 1 it learns QCs of epoch 1 only;  *)
(*   it signs only messages of its epoch.                                   *)
(* * One timeout per view and epoch: a node that timed out in a view and   *)
(*   then enters epoch 2 in that view may time out again there (lt is the  *)
(*   last one, as 3 * view + epoch).                                        *)
(* * Signed views are monotone (R3). LateVotes = FALSE allows a vote in    *)
(*   the node's current view only, as the prototype does.                   *)
(*                                                                         *)
(* Rules under test                                                         *)
(*   H5 = "none":   a certificate is counted under the table of its epoch.  *)
(*   H5 = "suffix": the QC of a suffix block and a TC embedded in a suffix  *)
(*                  block need a quorum of both tables (first draft).       *)
(*   H5 = "full":   every certificate of epoch 1 needs a quorum of both.    *)
(*   TcEpoch = "any":   a block may embed a TC of either epoch.             *)
(*   TcEpoch = "chain": the TC is of an epoch from the parent's to the      *)
(*                      block's (V3).                                       *)
(*   E4 = "vote": a vote of epoch 2 at a view not above a message of epoch 1*)
(*   E4 = "s16":  first draft -- any message of epoch 1 above one of epoch  *)
(*                2, or at the same view unless an old vote, a new timeout. *)
(*                                                                         *)
(* Invariants: NoHonestEvidence (lemma A: no honest node holds E1, E3, E4);*)
(* Accountable (lemma B: for every two conflicting direct commits and      *)
(* every choice of signer sets the case analysis applies and its culprit   *)
(* set holds more than 1/3 of W2 and no honest node); NoLedgerFork (no two *)
(* conflicting committed blocks of epoch 2).                                *)
(***************************************************************************)
EXTENDS Integers, FiniteSets, TLC

CONSTANTS Honest,      \* honest nodes (integers)
          Byz,         \* Byzantine nodes (integers)
          W1, W2,      \* weights of the old and the new table (tuples)
          V,           \* largest view
          H5,          \* "none", "suffix" or "full"
          TcEpoch,     \* "any" or "chain"
          E4,          \* "vote" or "s16"
          LateVotes    \* TRUE: votes for views below the current one, above every signed view

ASSUME Honest \cap Byz = {} /\ V \in Nat /\ LateVotes \in BOOLEAN
ASSUME H5 \in {"none", "suffix", "full"} /\ TcEpoch \in {"any", "chain"} /\ E4 \in {"vote", "s16"}

VARIABLES hs, votes, tmos
vars == <<hs, votes, tmos>>

Nodes == Honest \cup Byz
Max(a, b) == IF a > b THEN a ELSE b
Min(a, b) == IF a < b THEN a ELSE b

W(t) == IF t = 1 THEN W1 ELSE W2
RECURSIVE Weight(_, _)
Weight(S, t) == IF S = {} THEN 0
                ELSE LET x == CHOOSE y \in S : TRUE IN W(t)[x + 1] + Weight(S \ {x}, t)
Quorum(S, tables) == \A t \in tables : 3 * Weight(S, t) > 2 * Weight(Nodes, t)

G == <<0, "genesis", "none", 1>>
MaxB(a, b) == IF b[1] > a[1] THEN b ELSE a          \* higher view wins; ties keep a (R6)

\* The tables a certificate is counted under. ctx: the epoch of the block that embeds a TC (0: none).
QCTables(b) == IF b[4] = 1 /\ H5 # "none" THEN {1, 2} ELSE {b[4]}
TCTables(te, ctx) == IF te = 1 /\ (H5 = "full" \/ (H5 = "suffix" /\ ctx = 1)) THEN {1, 2} ELSE {te}
TCEpochs(be, pe) == IF TcEpoch = "any" THEN {1, 2} ELSE pe..be

Voters(b) == {k \in Honest : <<k, b>> \in votes}
QCok(b) == b = G \/ Quorum(Voters(b) \cup Byz, QCTables(b))
QCBlocks == {b \in {x[2] : x \in votes} \cup {G} : QCok(b)}
Low(v, te, m) == {k \in Honest : \E t \in tmos : t[1] = k /\ t[2] = v /\ t[4] = te /\ t[3] <= m}
TCok(v, te, m, ctx) == 0 <= m /\ m < v /\ Quorum(Low(v, te, m) \cup Byz, TCTables(te, ctx))

Constructible(v) ==
    LET qs == QCBlocks
        direct == {x \in {<<v, p, "none", eb>> : p \in {q \in qs : q[1] = v - 1}, eb \in 1..2} :
                      x[4] >= x[2][4]}
        viaTC == {x \in {<<v, p, <<q[1], q, te>>, eb>> : p \in qs, q \in qs, te \in 1..2, eb \in 1..2} :
                     /\ x[2][1] < v - 1
                     /\ x[4] >= x[2][4]
                     /\ x[3][3] \in TCEpochs(x[4], x[2][4])
                     /\ x[3][1] <= x[2][1]
                     /\ TCok(v - 1, x[3][3], x[3][1], x[4])}
    IN direct \cup viaTC

\* What a node of epoch ep that knows (h, hq) may know before it signs.
Learn(h, hq, ep) ==
    LET tces == IF TcEpoch = "any" THEN {1, 2} ELSE 1..ep
        cands == {hq} \cup {b \in QCBlocks : b[1] > hq[1] /\ b[4] <= ep}
    IN {o \in (0..V) \X cands :
          LET base == Max(h, o[2][1]) IN
          /\ o[1] >= base
          /\ \/ o[1] = base
             \/ \E q \in QCBlocks : \E te \in tces : TCok(o[1], te, q[1], 0) /\ q[1] <= o[2][1]}

\* The children X+ of the commit proofs of G a node of epoch 1 can hold.
Proofs == {c \in QCBlocks : c # G /\ c[4] = 1 /\ c[2] \in QCBlocks /\ c[1] = c[2][1] + 1}

LearnOptions(k) ==
    LET s == hs[k]
        own == {<<o[1], o[2], s.ep>> : o \in Learn(s.h, s.hq, s.ep)}
        enter == IF s.ep = 1
                 THEN UNION {{<<o[1], o[2], 2>> :
                                o \in Learn(Max(s.h, c[1]), IF c[1] > s.hq[1] THEN c ELSE s.hq, 2)} :
                             c \in Proofs}
                 ELSE {}
    IN own \cup enter

Init == /\ hs = [k \in Honest |-> [h |-> 0, hq |-> G, ell |-> 0, lt |-> 0, ep |-> 1]]
        /\ votes = {}
        /\ tmos = {}

Timeout(k) ==
    \E o \in LearnOptions(k) :
        LET v == o[1] + 1 IN
        /\ v <= V
        /\ hs[k].lt # v * 3 + o[3]
        /\ hs' = [hs EXCEPT ![k] = [h |-> o[1], hq |-> o[2], ell |-> Max(hs[k].ell, v),
                                    lt |-> v * 3 + o[3], ep |-> o[3]]]
        /\ tmos' = tmos \cup {<<k, v, o[2][1], o[3]>>}
        /\ UNCHANGED votes

Vote(k) ==
    \E o \in LearnOptions(k) :
        \E bv \in (IF LateVotes THEN hs[k].ell + 1 ELSE Max(hs[k].ell, o[1]) + 1)..Min(o[1] + 1, V) :
            \E b \in Constructible(bv) :
                 LET nhq0 == MaxB(o[2], b[2])
                     nhq == IF b[3] # "none" THEN MaxB(nhq0, b[3][2]) ELSE nhq0
                 IN /\ b[4] = o[3]
                    /\ hs' = [hs EXCEPT ![k] = [h |-> Max(o[1], bv - 1), hq |-> nhq, ell |-> bv,
                                                lt |-> hs[k].lt, ep |-> o[3]]]
                    /\ votes' = votes \cup {<<k, b>>}
                    /\ UNCHANGED tmos

Next == \E k \in Honest : Timeout(k) \/ Vote(k)
Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
(* Checks *)

\* Lemma A. E1: two votes of one view and epoch. E3: a vote for a block with justify view j and a timeout of
\* the same or a later epoch at a view at least as high reporting hq < j. E4: see the header.
NoHonestE1 == \A x \in votes : \A y \in votes :
                  (x[1] = y[1] /\ x[2][1] = y[2][1] /\ x[2][4] = y[2][4]) => x[2] = y[2]
NoHonestE3 == \A x \in votes : \A t \in tmos :
                  (t[1] = x[1] /\ t[4] >= x[2][4] /\ t[2] >= x[2][1]) => t[3] >= x[2][2][1]
\* Messages of node k in epoch e as <<kind, view>>.
Msgs(k, e) == {<<"vote", x[2][1]>> : x \in {y \in votes : y[1] = k /\ y[2][4] = e}}
              \cup {<<"timeout", t[2]>> : t \in {s \in tmos : s[1] = k /\ s[4] = e}}
E4Hit(old, new) == IF E4 = "vote" THEN new[1] = "vote" /\ old[2] >= new[2]
                   ELSE old[2] > new[2] \/ (old[2] = new[2] /\ ~(old[1] = "vote" /\ new[1] = "timeout"))
NoHonestE4 == \A k \in Honest : \A old \in Msgs(k, 1) : \A new \in Msgs(k, 2) : ~E4Hit(old, new)
NoHonestEvidence == NoHonestE1 /\ NoHonestE3 /\ NoHonestE4

RECURSIVE Anc(_, _)
Anc(a, b) == IF b = a THEN TRUE ELSE IF b[1] = 0 THEN FALSE ELSE Anc(a, b[2])
Conflicting(x, y) == ~Anc(x, y) /\ ~Anc(y, x)

Commits == {c \in QCBlocks \X QCBlocks : c[2] # G /\ c[2][2] = c[1] /\ c[2][1] = c[1][1] + 1}
Q(b) == {S \in SUBSET (Voters(b) \cup Byz) : Quorum(S, QCTables(b))}
GoodC(C) == C \cap Honest = {} /\ 3 * Weight(C, 2) > Weight(Nodes, 2)

RECURSIVE Zof(_, _)
Zof(b, u) == IF b[2][1] > u + 1 THEN Zof(b[2], u) ELSE b   \* ancestor with the smallest view above u+1

Judge(cx, cy) ==
    LET X == cx[1]
        Xp == cx[2]
        Y == cy[1]
        u == X[1]
        Z == Zof(Y, u)
        P == Z[2]
        j == P[1]
        w == Z[1]
        TQ == {S \in SUBSET (Low(w - 1, Z[3][3], Z[3][1]) \cup Byz) : Quorum(S, TCTables(Z[3][3], Z[4]))}
    IN
    IF Y[1] = u THEN \A q1 \in Q(X) : \A qy \in Q(Y) : GoodC(q1 \cap qy)                \* A: E1 or E4
    ELSE IF Y[1] = u + 1 THEN \A q2 \in Q(Xp) : \A qy \in Q(Y) : GoodC(q2 \cap qy)      \* B: E1 or E4
    ELSE IF j = u + 1 THEN P # Xp /\ \A q2 \in Q(Xp) : \A qz \in Q(P) : GoodC(q2 \cap qz)  \* C1
    ELSE IF j = u THEN P # X /\ \A q1 \in Q(X) : \A qz \in Q(P) : GoodC(q1 \cap qz)        \* C2
    ELSE /\ Z[3] # "none"                                                                  \* C3: E3 or E4
         /\ Z[3][1] <= j
         /\ \A q2 \in Q(Xp) : \A t \in TQ : GoodC(q2 \cap t)

Accountable == \A cx \in Commits : \A cy \in Commits :
                   (Conflicting(cx[1], cy[1]) /\ cx[1][1] <= cy[1][1]) => Judge(cx, cy)

NoLedgerFork == \A cx \in Commits : \A cy \in Commits :
                    ~(cx[1][4] = 2 /\ cy[1][4] = 2 /\ Conflicting(cx[1], cy[1]))
=============================================================================
