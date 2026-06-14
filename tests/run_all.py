"""
Runner testów jednostkowych tutamcp (bez dostępu do sieci).

Uruchamia wszystkie testy z prefiksem test_*.py.
Testy integracyjne (it_*.py) wymagają danych logowania — uruchamiaj osobno.

Uruchamianie:
    /usr/bin/python3.11 run.py tests/run_all.py
"""

import sys
import os
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    import importlib.util

    # Zbierz wszystkie moduły test_*.py z katalogu tests/
    for fname in sorted(os.listdir(_TESTS_DIR)):
        if not fname.startswith("test_") or not fname.endswith(".py"):
            continue
        module_name = fname[:-3]
        print(f"Ładuję: {module_name}")
        spec = importlib.util.spec_from_file_location(
            module_name, os.path.join(_TESTS_DIR, fname)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        suite.addTests(loader.loadTestsFromModule(mod))

    print(f"\nUruchamiam {suite.countTestCases()} testów jednostkowych...\n")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
