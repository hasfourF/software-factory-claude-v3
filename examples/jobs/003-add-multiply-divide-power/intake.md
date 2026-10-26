DECISION: ACCEPT
RISK: low
SURFACES: none
RESCOPED: yes

## Scope
Build the first slice of the calculator in `calc.py`: three new functions, each with unit tests in `tests/test_calc.py`.

- `multiply(a, b)`: returns `a * b`.
- `divide(a, b)`: returns `a / b`. When `b` is zero, raise `ValueError` with a clear message (for example "cannot divide by zero"). Do not return infinity or `None`.
- `power(a, b)`: returns `a ** b`. No special-casing.

Tests: one or more assertions per function in `tests/test_calc.py`, following the existing `AddTest` style (for example a `MultiplyTest`, `DivideTest`, `PowerTest` class). The divide-by-zero case must be covered with `assertRaises(ValueError)`. Run `python3 -m unittest discover -s tests -t .` (or `factory/checks.sh`) to verify.

Left out, for later issues or slices:
- `sqrt`, `log`, `sin`/`cos`/`tan`.
- The expression parser with parentheses and operator precedence.
- The interactive REPL.
- Any change to `web/index.html`. The page keeps its current add-only form.

Keep the change to `calc.py` and `tests/test_calc.py`. Standard library only.

## Why
The issue bundles at least five separate features (arithmetic, scientific functions, a parser, and a REPL), which would be too large for one reviewable pull request. `calc.py` currently has only `add`, and every function must have a test in `tests/`, as AGENTS.md requires. Multiply, divide and power are small, pure functions that fit that pattern, so they make a self-contained first slice that the later parts can build on.

## Questions
