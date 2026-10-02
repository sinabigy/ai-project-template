# Template changelog

## 1.0.1
Fixes found by dogfooding the first real retrofit:
- **Self-test isolation.**
  - Retrofits no longer copy `tools/tests/` into projects.
  - The self-test file is renamed to `template_selftest.py`, so a project's pytest or unittest never collects it.
  - The self-tests skip outside an uninitialized template.
- **Declared pytest `testpaths`.** `ai-map` now honours `testpaths` from `pytest.ini`, `pyproject.toml`, `tox.ini` or `setup.cfg`, using pytest's own precedence. A filename that merely matches `*_test.py` outside those paths no longer makes its folder a test path. The map records the source as `test_config`. Without declared `testpaths`, the filename heuristics are unchanged.
- **Summaries README in retrofits.** Retrofits now include `.ai/context/summaries/README.md`, but never result packets.
- Mapper version is now 1.0.1, so maps made by 1.0.0 are reported as needing a refresh.

## 1.0.0
- First release:
  - Portable protocol (`AI_PROTOCOL.md`).
  - JSON canonical state with JSON Schema 2020-12.
  - Capability routing with a local runtime registry.
  - Tools: `ai-init`, `ai-check`, `ai-map`, `ai-task`, `ai-route`.
  - Thin provider shims.
