# Dirty on purpose: is_negative is still declared, negated survives only in comments.
# def negated(value):
#     return -value


def is_negative(value):
    return value < 0  # negated(value) would read the sign the other way
