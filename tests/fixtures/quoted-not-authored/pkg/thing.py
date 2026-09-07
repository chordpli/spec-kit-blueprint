class Thing:
    def compute(self, a, b):
        raise NotImplementedError(
            "T001: add a and b, and refuse a negative result - the caller treats a "
            "negative as a programming error rather than a value (010 FR-001)."
        )
