class Store:
    def put(self, key, record, overwrite):
        raise NotImplementedError(
            "T001: store the record under key, and when the key is already present "
            "honour overwrite rather than deciding for the caller; the two callers "
            "disagree about which is right, which is why it is a parameter "
            "(012 FR-001)."
        )
