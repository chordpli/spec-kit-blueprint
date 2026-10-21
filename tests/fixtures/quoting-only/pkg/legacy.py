def render(rows):
    # moved verbatim from the old module
    if not rows:
        return ""
    return ",".join(rows)


def width(rows):
    raise NotImplementedError(
        "an earlier feature left this one, and its message names no task at all"
    )
