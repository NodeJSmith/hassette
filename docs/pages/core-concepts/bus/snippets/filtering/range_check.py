from hassette import A, C, P

# --8<-- [start:range_check]
P.AllOf((
    P.ValueIs(source=A.get_state_value_new, condition=C.Comparison(">=", 18)),
    P.ValueIs(source=A.get_state_value_new, condition=C.Comparison("<=", 26)),
))
# --8<-- [end:range_check]
