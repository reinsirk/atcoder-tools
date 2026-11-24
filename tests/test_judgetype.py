import unittest

from atcodertools.common.judgetype import NormalJudge


OTHER_WHITESPACE = (
    "\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000"
)


class TestNormalJudge(unittest.TestCase):
    def test_default_comparison_is_exact(self):
        judge = NormalJudge()
        self.assertTrue(judge.verify("1 2\n", "1 2\n"))
        self.assertFalse(judge.verify("1 2 \n", "1 2\n"))
        self.assertFalse(judge.verify("", "\n"))

    def test_exact_comparison(self):
        judge = NormalJudge(ignore_whitespace=False)
        for output in ["", "1 2\n", "1\t2\r\n", "a\u3000b"]:
            with self.subTest(output=output):
                self.assertTrue(judge.verify(output, output))
        for whitespace in " \t\r\n":
            cases = [
                (whitespace + "1 2", "1 2"),
                ("1 2" + whitespace, "1 2"),
                ("1" + whitespace + "2", "1  2"),
                (whitespace, ""),
            ]
            for output, expected in cases:
                with self.subTest(output=output, expected=expected):
                    self.assertFalse(judge.verify(output, expected))
                    self.assertFalse(judge.verify(expected, output))

    def test_serialization_preserves_comparison_mode(self):
        for ignore_whitespace in [True, False]:
            with self.subTest(ignore_whitespace=ignore_whitespace):
                judge = NormalJudge(ignore_whitespace=ignore_whitespace)
                restored = NormalJudge.from_dict(judge.to_dict())
                self.assertEqual(ignore_whitespace,
                                 restored.verify("1 \n", "1\n"))
        self.assertEqual({"judge_type": "normal"}, NormalJudge().to_dict())
        legacy = NormalJudge.from_dict({"judge_type": "normal"})
        self.assertFalse(legacy.verify("1 \n", "1\n"))

    def test_ignores_each_allowed_whitespace(self):
        judge = NormalJudge(ignore_whitespace=True)
        for whitespace in " \t\r\n":
            with self.subTest(whitespace=whitespace):
                output = whitespace + "1" + whitespace * 2 + "2" + whitespace
                self.assertTrue(judge.verify(output, "1 2\n"))
                self.assertTrue(judge.verify("1 2\n", output))
                self.assertTrue(judge.verify(whitespace, ""))

    def test_ignores_whitespace(self):
        judge = NormalJudge(ignore_whitespace=True)
        cases = [
            ("1 2\n", "1 2\n"),
            ("1 2", "1 2\n"),
            ("  1 2  \n", "1 2\n"),
            ("1   2\n", "1 2\n"),
            ("1\t2\r\n", "1 2\n"),
            ("\n1\n\n2\n\n", "1 2\n"),
            ("Yes\n No", "Yes No\n"),
            ("", " \t\r\n"),
        ]
        for output, expected in cases:
            with self.subTest(output=output, expected=expected):
                self.assertTrue(judge.verify(output, expected))
                self.assertTrue(judge.verify(expected, output))

    def test_rejects_different_tokens(self):
        judge = NormalJudge(ignore_whitespace=True)
        cases = [
            ("1 3\n", "1 2\n"),
            ("2 1\n", "1 2\n"),
            ("1 2 3\n", "1 2\n"),
            ("1\n", "1 2\n"),
            ("12\n", "1 2\n"),
            ("Yes\n", "yes\n"),
            ("1.0\n", "1\n"),
            ("", "1\n"),
        ]
        for output, expected in cases:
            with self.subTest(output=output, expected=expected):
                self.assertFalse(judge.verify(output, expected))
                self.assertFalse(judge.verify(expected, output))

    def test_does_not_ignore_other_whitespace(self):
        judge = NormalJudge(ignore_whitespace=True)
        for whitespace in OTHER_WHITESPACE:
            cases = [
                ("1" + whitespace + "2", "1 2"),
                (whitespace + "1", "1"),
                ("1" + whitespace, "1"),
                (whitespace, ""),
                ("ab" + whitespace + "cd", "abcd"),
            ]
            for output, expected in cases:
                with self.subTest(output=output, expected=expected):
                    self.assertFalse(judge.verify(output, expected))
                    self.assertFalse(judge.verify(expected, output))

    def test_preserves_other_whitespace_in_tokens(self):
        judge = NormalJudge(ignore_whitespace=True)
        for whitespace in OTHER_WHITESPACE:
            expected = "a" + whitespace + "b"
            with self.subTest(whitespace=whitespace):
                self.assertTrue(judge.verify(expected, expected))
                self.assertTrue(judge.verify(
                    " \t" + expected + "\r\n", expected))
                self.assertTrue(judge.verify(
                    expected, " \t" + expected + "\r\n"))
