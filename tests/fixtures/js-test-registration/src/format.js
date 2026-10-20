// Dirty on purpose: the blueprint declares formatRow and this file renamed it, so
// --done must still fail here while it stops failing on the test registration call.
export function formatLine(row) { return row.join(","); }
