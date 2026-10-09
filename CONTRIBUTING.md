# Contributing

The Bold API client and Bluetooth protocol live in
`custom_components/bold/boldsmartlock/`, which doesn't depend on Home Assistant,
so in the future it can become a standalone library (as Home Assistant core
requires). A test keeps it that way.

```sh
pip install -r requirements_test.txt pre-commit
pre-commit install  # runs ruff and mypy before each commit
pytest --cov=custom_components.bold
python script/translations.py  # after changing strings.json
pytest --snapshot-update  # after changing entities or diagnostics; review the diff
HYPOTHESIS_PROFILE=thorough pytest tests/test_fuzz.py  # after changing parsing
```

CI requires 100% test coverage, and also runs the tests against the oldest
Home Assistant version in `hacs.json`.
