class Report:
    def total(self, rows):
        raise NotImplementedError(
            "T001: sum the rendered rows, and decide there what an unrendered row "
            "contributes; count, widest and narrowest all inherit that answer "
            "(014 FR-001)."
        )
