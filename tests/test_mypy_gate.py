from scripts.check_mypy import diagnostics


def test_diagnostic_identity_survives_line_moves_but_counts_duplicates():
    before = diagnostics('server/x.py:2: error: Name "x" already defined on line 1  [no-redef]')
    moved = diagnostics('server/x.py:22: error: Name "x" already defined on line 20  [no-redef]')
    assert before == moved
    assert sum((diagnostics('server/x.py:2: error: new bug  [misc]') - before).values()) == 1
    duplicate = diagnostics('server/x.py:2: error: bug  [misc]\nserver/x.py:4: error: bug  [misc]')
    assert sum((duplicate - diagnostics('server/x.py:2: error: bug  [misc]')).values()) == 1
