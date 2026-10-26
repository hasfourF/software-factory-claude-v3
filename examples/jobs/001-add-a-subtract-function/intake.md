DECISION: ACCEPT
RISK: low
SURFACES: none
RESCOPED: no

## Scope
Add `subtract(a, b)` to `calc.py`, returning `a - b`, placed after `add()` and using the same style (a docstring-free one-line body). Add a test for it in `tests/test_calc.py`, following the existing `AddTest` pattern: a `SubtractTest` class (or a `test_subtract` method alongside `test_add`) that asserts `subtract(5, 3) == 2`.

Left out: no changes to `web/index.html`, no UI for subtraction, no handling of non-numeric input or other operations.

## Why
`calc.py` contains only `add()`, and `AGENTS.md` requires every function in `calc.py` to have a test in `tests/`, so the test is part of the request. The change is one function and one test on the standard library, with no shared or sensitive code involved.
