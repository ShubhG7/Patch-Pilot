from agent.graph import _extract_diff, _fix_hunk_headers


def test_extract_diff_from_json_wrapper_with_escaped_newlines() -> None:
    text = '{"diff": "--- a/src/demo_app/calculator.py\\n+++ b/src/demo_app/calculator.py\\n@@ -1,1 +1,1 @@\\n-x\\n+y\\n"}'
    diff = _extract_diff(text)
    assert diff.startswith("--- a/src/demo_app/calculator.py")
    assert "+++ b/src/demo_app/calculator.py" in diff
    assert "@@" in diff


def test_fix_hunk_headers_corrects_wrong_counts() -> None:
    # Model says @@ -15,7 +15,7 @@ but actual content has 6 old, 5 new
    bad_diff = """--- a/src/demo_app/calculator.py
+++ b/src/demo_app/calculator.py
@@ -15,7 +15,7 @@
         ZeroDivisionError: if b is 0.
     \"\"\"
     if b == 0:
-        # BUG (seed/issue-1): should raise, but returns 0.0
-        return 0.0
+        raise ZeroDivisionError("Cannot divide by zero")
     return a / b"""
    fixed = _fix_hunk_headers(bad_diff)
    # Should have corrected to @@ -15,6 +15,5 @@
    assert "@@ -15,6 +15,5 @@" in fixed


def test_fix_hunk_headers_preserves_correct_counts() -> None:
    # Already correct counts
    good_diff = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line1
-old
+new
 line3"""
    fixed = _fix_hunk_headers(good_diff)
    assert "@@ -1,3 +1,3 @@" in fixed

