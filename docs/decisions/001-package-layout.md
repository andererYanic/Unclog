# 001 — Package layout under `src/unclog/`

**Status:** accepted · 2026-11-05

The brief (§17) puts the modules straight under `src/` (`src/flow/`, `src/build/`, …). Top-level
package names like `build`, `store`, `flow` and `evals` collide with PyPI packages and stdlib-adjacent
names once installed. So every module lives one level down at `src/unclog/<module>/`, and the
module names and boundaries stay exactly as the brief has them. Root folders `prompts/`, `knowledge/`,
`templates/`, `evals/`, `tests/` and `clients/` (gitignored) are unchanged.

JSON Schemas are generated from the Pydantic models (`unclog-export-schemas <dir>`). Pydantic is the
source of truth, so the two can't drift.
