// Dirty on purpose. doubled and tripled are declared as bindings, which is the same
// declaration in another form, so --done must accept them. halved was deleted and only
// its header survives inside a comment, so --done must still report it missing.
export const doubled = (value) => {
  return value * 2;
};

export const tripled = function (value) {
  return value * 3;
};

// export function halved(value) { -- removed
/* export function halved(value) {
   return value / 2;
} */
const url = "http://example.invalid/halved(value)";
