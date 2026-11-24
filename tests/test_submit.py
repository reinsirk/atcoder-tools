import os
import unittest
import shutil
import sys
import tempfile
from unittest.mock import MagicMock
from atcodertools.tools import submit

RESOURCE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "./resources/test_submit/"))


def fake_cookie_supplier():
    from http.cookiejar import Cookie
    return Cookie(
        version=0,
        name='REVEL_SESSION',
        value="@@@ invalid cookie @@@",
        port=None,
        port_specified=False,
        domain='atcoder.jp',
        domain_specified=True,
        domain_initial_dot=False,
        path='/',
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False
    )


class TestTester(unittest.TestCase):

    def test_submission_uses_whitespace_option_from_config(self):
        with tempfile.TemporaryDirectory() as test_dir:
            shutil.copytree(os.path.join(
                RESOURCE_DIR, 'with_metadata'), test_dir, dirs_exist_ok=True)
            source = os.path.join(test_dir, 'main.py')
            with open(source, 'w') as f:
                f.write("print(sum(map(int, input().split())), end=' \\n')\n")
            for number in [1, 2]:
                with open(os.path.join(test_dir, '{}.in'.format(number)), 'w') as f:
                    f.write('1 2\n')
                with open(os.path.join(test_dir, '{}.out'.format(number)), 'w') as f:
                    f.write('3\n')
            config_path = os.path.join(test_dir, 'config.toml')
            for ignore_whitespace in [None, False, True]:
                with open(config_path, 'w') as f:
                    f.write('[tester]\n')
                    if ignore_whitespace is not None:
                        f.write('ignore_whitespace={}\n'.format(
                            str(ignore_whitespace).lower()))
                client = MagicMock()
                with self.subTest(ignore_whitespace=ignore_whitespace):
                    submit.main('', ['-d', test_dir, '-e', '{} {}'.format(sys.executable, source),
                                     '--config', config_path, '-u'], client=client)
                    self.assertEqual(int(bool(ignore_whitespace)),
                                     client.submit_source_code.call_count)

    def test_submit_fail_when_metadata_not_found(self):
        ok = submit.main(
            '', ['-d', os.path.join(RESOURCE_DIR, "without_metadata")], fake_cookie_supplier, False)
        self.assertFalse(ok)

    def test_test_fail(self):
        ok = submit.main(
            '', ['-d', os.path.join(RESOURCE_DIR, "with_metadata")], fake_cookie_supplier, False)
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
