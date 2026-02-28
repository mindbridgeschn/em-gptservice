% Complexity ranking
complexity_rank(straightforward, 1).
complexity_rank(low, 2).
complexity_rank(moderate, 3).
complexity_rank(high, 4).

% Define complexity levels for different problem types
complexity(self_limited_minor, N, straightforward) :- N =< 1.
complexity(self_limited_minor, N, low) :- N > 1.

complexity(stable_chronic, N, low) :- N =< 1.
complexity(stable_chronic, N, moderate) :- N > 1.

complexity(acute_uncomplicated, N, low) :- N >= 1.

complexity(stable_acute, N, moderate) :- N >= 1.

complexity(acute_uncomplicated_hospital, N, moderate) :- N >= 1.

complexity(chronic_exacerbation, N, moderate) :- N >= 1.

complexity(undiagnosed_new, N, moderate) :- N >= 1.

complexity(acute_systemic, N, moderate) :- N >= 1.

complexity(acute_complicated_injury, N, moderate) :- N >= 1.

complexity(chronic_severe, N, high) :- N >= 1.

complexity(threatening_illness, N, high) :- N >= 1.

get_complexity(problem(Type, N), Level) :- complexity(Type, N, Level).
get_complexity((Type, N), Level) :- complexity(Type, N, Level).

get_all_complexities([], []).
get_all_complexities([P|Ps], [L|Ls]) :-
    get_complexity(P, L),
    get_all_complexities(Ps, Ls).


max_complexity([C], C).
max_complexity([C1, C2 | Rest], Max) :-
    complexity_rank(C1, R1),
    complexity_rank(C2, R2),
    (R1 >= R2 -> MaxC = C1 ; MaxC = C2),
    max_complexity([MaxC | Rest], Max).

highest_complexity_from_list([], straightforward).
highest_complexity_from_list(ProblemList, MaxComplexity) :-
    ProblemList \= [],
    get_all_complexities(ProblemList, Levels),
    max_complexity(Levels, MaxComplexity).
