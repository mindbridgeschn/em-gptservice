% mo(A,B,C,D,E,F, Result).

mo(A, B, C, D, E, F, "Straight Forward") :-
    Group1 is A + B + C,
    Group2 is D,
    Group3 is E + F,
    Group3 =:= 0,
    Group1 =< 1,
    Group2 =:= 0.

mo(A, B, C, D, E, F, "Low") :-
    Group1 is A + B + C,
    Group2 is D,
    Group3 is E + F,
    Group3 =:= 0,
    Group1 =< 2,
    Group2 =:= 0,
    Group1 > 1.

mo(A, B, C, D, E, F, "Moderate") :-
    Group1 is A + B + C,
    Group2 is D,
    Group3 is E + F,
    Group3 =:= 0,
    (Group1 > 2 ; Group2 =\= 0).

mo(A, B, C, D, E, F, "Moderate") :-
    Group1 is A + B + C,
    Group2 is D,
    Group3 is E + F,
    Group3 =:= 1,
    Group1 =< 2,
    Group2 =:= 0.

mo(A, B, C, D, E, F, "High") :-
    Group1 is A + B + C,
    Group2 is D,
    Group3 is E + F,
    Group3 =:= 1,
    (Group1 > 2 ; Group2 =\= 0).

mo(A, B, C, D, E, F, "Moderate") :-
    Group1 is A + B + C,
    Group3 is E + F,
    Group3 =:= 2,
    Group1 =< 1.

mo(A, B, C, D, E, F, "High") :-
    Group1 is A + B + C,
    Group3 is E + F,
    Group3 =:= 2,
    Group1 > 1.
