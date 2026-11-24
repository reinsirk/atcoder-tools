import os
import unittest
import shutil
import tempfile
import io
import sys
from argparse import Namespace

from colorama import Fore
from unittest.mock import patch, mock_open, MagicMock

from atcodertools.executils.run_program import ExecResult, ExecStatus
from atcodertools.tools import tester
from atcodertools.tools.tester import is_executable_file, TestSummary, build_details_str
from atcodertools.tools.utils import with_color
from atcodertools.common.language import ALL_LANGUAGES, CPP
from atcodertools.common.judgetype import DecimalJudge
from atcodertools.tools.models.metadata import DEFAULT_METADATA, Metadata
from atcodertools.tools.compiler import compile_main_and_judge_programs

RESOURCE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "./resources/test_tester/"))


class TestTester(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def test_multiple_exec_files(self):
        all_ok = tester.main(
            '', ['-d', os.path.join(RESOURCE_DIR, "test_multiple_exec_files")])
        self.assertTrue(all_ok)

    def test_run_single_test(self):
        test_dir = os.path.join(RESOURCE_DIR, "test_run_single_test")
        self.assertTrue(tester.main('', ['-d', test_dir, "-n", "1"]))
        self.assertFalse(tester.main('', ['-d', test_dir, "-n", "2"]))

    def test_normal_judge_defaults_to_exact_comparison(self):
        with tempfile.TemporaryDirectory() as test_dir:
            source = os.path.join(test_dir, 'main.py')
            with open(source, 'w') as f:
                f.write("import sys\nsys.stdout.write('  1 \\t2  \\n\\n3  ')")
            with open(os.path.join(test_dir, 'in_1.txt'), 'w') as f:
                f.write('')
            with open(os.path.join(test_dir, 'out_1.txt'), 'w') as f:
                f.write('1 2\n3\n')

            args = ['-d', test_dir, '-e',
                    '{} {}'.format(sys.executable, source),
                    '--config', tester.get_default_config_path()]
            self.assertFalse(tester.main('', args))
            self.assertFalse(tester.main(
                '', args + ['-n', '1', '-j', 'normal']))

    def test_whitespace_comparison_option(self):
        with tempfile.TemporaryDirectory() as test_dir:
            source = os.path.join(test_dir, 'main.py')
            with open(source, 'w') as f:
                f.write('import sys\nsys.stdout.write(sys.stdin.read())\n')
            config_path = os.path.join(test_dir, 'config.toml')
            args = ['-d', test_dir, '-e', '{} {}'.format(sys.executable, source),
                    '--config', config_path]
            cases = [
                ('1 2\n', '1 2\n', True, True),
                (' 1\t2 \n', '1 2\n', False, True),
                ('1 2', '1 2\n', False, True),
                ('', '\n', False, True),
                ('1\u30002\n', '1 2\n', False, False),
                ('1 3\n', '1 2\n', False, False),
            ]
            for ignore_whitespace in [None, False, True]:
                with open(config_path, 'w') as f:
                    f.write('[tester]\n')
                    if ignore_whitespace is not None:
                        f.write('ignore_whitespace={}\n'.format(
                            str(ignore_whitespace).lower()))
                for output, expected, exact_match, relaxed_match in cases:
                    with open(os.path.join(test_dir, 'in_1.txt'), 'w') as f:
                        f.write(output)
                    with open(os.path.join(test_dir, 'out_1.txt'), 'w') as f:
                        f.write(expected)
                    correct = relaxed_match if ignore_whitespace else exact_match
                    for options in [[], ['-n', '1', '-j', 'normal']]:
                        with self.subTest(ignore_whitespace=ignore_whitespace, output=output, options=options):
                            self.assertEqual(
                                correct, tester.main('', args + options))
            self.assertFalse(DEFAULT_METADATA.judge_method.ignore_whitespace)

    def test_decimal_judge_is_unaffected_by_whitespace_option(self):
        args = Namespace(judge_type=None, error_value=None)
        metadata = Metadata(None, None, 'in_*.txt', 'out_*.txt',
                            CPP, DecimalJudge(diff=0.01))
        for judge_type in [None, 'absolute', 'relative', 'absolute_or_relative']:
            args.judge_type = judge_type
            with self.subTest(judge_type=judge_type):
                judge = tester._decide_judge_method(
                    args, metadata, metadata.lang, ignore_whitespace=False)
                self.assertIsInstance(judge, DecimalJudge)
                self.assertTrue(judge.verify(' 1.001 \n', '1.0\n'))

    def test_run_single_test_decimal_addition(self):
        test_dir = os.path.join(
            RESOURCE_DIR, "test_run_single_test_decimal_addition")
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "1", "-v", "0.01", "-j", "absolute_or_relative"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "2", "-v", "0.01", "--judge-type", "absolute_or_relative"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "1", "-v", "0.01", "-j", "absolute"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "2", "-v", "0.01", "-j", "absolute"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "1", "-v", "0.01", "-j", "relative"]))
        self.assertFalse(tester.main(
            '', ['-d', test_dir, "-n", "2", "-v", "0.01", "-j", "relative"]))

    def test_run_single_test_decimal_multiplication(self):
        test_dir = os.path.join(
            RESOURCE_DIR, "test_run_single_test_decimal_multiplication")
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "1", "-v", "0.01", "-j", "absolute_or_relative"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "2", "--error-value", "0.01", "-j", "absolute_or_relative"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "1", "-v", "0.01", "-j", "absolute"]))
        self.assertFalse(tester.main(
            '', ['-d', test_dir, "-n", "2", "-v", "0.01", "-j", "absolute"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "1", "-v", "0.01", "-j", "relative"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "-n", "2", "-v", "0.01", "-j", "relative"]))

    @patch('os.access', return_value=True)
    @patch('pathlib.Path.is_file', return_value=True)
    def test_is_executable_file(self, os_mock, is_file_mock):
        self.assertTrue(is_executable_file('a.out'))

    @patch('os.access', return_value=False)
    @patch('pathlib.Path.is_file', return_value=True)
    def test_is_executable_file__not_executable(self, os_mock, is_file_mock):
        self.assertFalse(is_executable_file('a.out'))

    @patch('os.access', return_value=True)
    @patch('pathlib.Path.is_file', return_value=True)
    def test_is_executable_file__source_code(self, os_mock, is_file_mock):
        self.assertFalse(is_executable_file('A.cpp'))

    @patch('os.access', return_value=True)
    @patch('pathlib.Path.is_file', return_value=True)
    def test_is_executable_file__text(self, os_mock, is_file_mock):
        self.assertFalse(is_executable_file('in.txt'))

    @patch('os.access', return_value=True)
    @patch('pathlib.Path.is_file', return_value=False)
    def test_is_executable_file__directory(self, os_mock, is_file_mock):
        self.assertFalse(is_executable_file('directory'))

    @patch("platform.system", return_value="Windows")
    @patch("os.environ.get", return_value=".EXE;.out")
    def test_is_executable_file__windows(self, platform_system_mock, os_environ_get_mock):
        self.assertTrue(is_executable_file("A.eXe"))
        self.assertTrue(is_executable_file("A.out"))
        self.assertFalse(is_executable_file("A.exe.bak"))

    @patch('atcodertools.tools.tester.run_program', return_value=ExecResult(ExecStatus.NORMAL, 'correct', '', 0))
    def test_run_for_samples(self, run_program_mock: MagicMock):
        io_mock = mock_open(read_data='correct')

        with patch('atcodertools.tools.tester.open', io_mock):
            self.assertEqual(TestSummary(1, False), tester.run_for_samples(
                'a.out', [('in_1.txt', 'out_1.txt')], 1))
            self.assertEqual(1, run_program_mock.call_count)

    @patch('atcodertools.tools.tester.build_details_str', return_value='')
    @patch('atcodertools.tools.tester.run_program', return_value=ExecResult(ExecStatus.NORMAL, 'correct', 'stderr', 0))
    def test_run_for_samples__with_stderr(self, run_program_mock: MagicMock, build_details_str_mock: MagicMock):
        io_mock = mock_open(read_data='correct')

        with patch('atcodertools.tools.tester.open', io_mock):
            self.assertEqual(TestSummary(1, True), tester.run_for_samples(
                'a.out', [('in_1.txt', 'out_1.txt')], 1))
            self.assertEqual(1, run_program_mock.call_count)
            self.assertEqual(1, build_details_str_mock.call_count)

    @patch('atcodertools.tools.tester.build_details_str', return_value='')
    @patch('atcodertools.tools.tester.run_program', return_value=ExecResult(ExecStatus.NORMAL, 'wrong', '', 0))
    def test_run_for_samples__wrong_answer(self, run_program_mock: MagicMock, build_details_str_mock: MagicMock):
        io_mock = mock_open(read_data='correct')

        with patch('atcodertools.tools.tester.open', io_mock):
            self.assertEqual(TestSummary(0, False), tester.run_for_samples(
                'a.out', [('in_1.txt', 'out_1.txt')], 1))
            self.assertEqual(1, run_program_mock.call_count)
            self.assertEqual(1, build_details_str_mock.call_count)

    @patch('atcodertools.tools.tester.build_details_str', return_value='')
    @patch('atcodertools.tools.tester.run_program', return_value=ExecResult(ExecStatus.NORMAL, 'wrong', '', 0))
    def test_run_for_samples__stop_execution_on_first_failure(self, run_program_mock: MagicMock,
                                                              build_details_str_mock: MagicMock):
        io_mock = mock_open(read_data='correct')

        with patch('atcodertools.tools.tester.open', io_mock):
            sample_pair_list = [('in_1.txt', 'out_1.txt'),
                                ('in_2.txt', 'out_2.txt')]
            self.assertEqual(TestSummary(0, False), tester.run_for_samples(
                'a.out', sample_pair_list, 1, knock_out=True))
            self.assertEqual(1, run_program_mock.call_count)
            self.assertEqual(1, build_details_str_mock.call_count)

    @patch('atcodertools.tools.tester.build_details_str', return_value='')
    @patch('atcodertools.tools.tester.run_program', return_value=ExecResult(ExecStatus.NORMAL, 'correct', 'stderr', 0))
    def test_run_for_samples__skip_stderr(self, run_program_mock: MagicMock, build_details_str_mock: MagicMock):
        io_mock = mock_open(read_data='correct')

        with patch('atcodertools.tools.tester.open', io_mock):
            self.assertEqual(TestSummary(1, True), tester.run_for_samples(
                'a.out', [('in_1.txt', 'out_1.txt')], 1, skip_io_on_success=True))
            self.assertEqual(1, run_program_mock.call_count)
            self.assertEqual(0, build_details_str_mock.call_count)

    def test_build_details_str(self):
        in_out = 'correct\n'
        output = 'wrong\n'
        stderr = 'stderr\n'
        expected = (with_color('[Input]', Fore.LIGHTMAGENTA_EX) + '\n'
                    + in_out + with_color('[Expected]',
                                          Fore.LIGHTMAGENTA_EX) + '\n' + in_out
                    + with_color('[Received]',
                                 Fore.LIGHTMAGENTA_EX) + '\n' + output
                    + with_color('[Error]', Fore.LIGHTYELLOW_EX) + '\n' + stderr)
        io_mock = mock_open(read_data=in_out)

        with patch('atcodertools.tools.tester.open', io_mock):
            result = build_details_str(ExecResult(
                ExecStatus.NORMAL, output, stderr), 'in.txt', 'out.txt')
            self.assertEqual(expected, result)

    def test_build_details_str__show_testcase_if_there_is_stderr(self):
        in_out = 'correct\n'
        stderr = 'stderr\n'
        expected = (with_color('[Input]', Fore.LIGHTMAGENTA_EX) + '\n'
                    + in_out + with_color('[Expected]',
                                          Fore.LIGHTMAGENTA_EX) + '\n' + in_out
                    + with_color('[Received]',
                                 Fore.LIGHTMAGENTA_EX) + '\n' + in_out
                    + with_color('[Error]', Fore.LIGHTYELLOW_EX) + '\n' + stderr)
        io_mock = mock_open(read_data=in_out)

        with patch('atcodertools.tools.tester.open', io_mock):
            result = build_details_str(ExecResult(
                ExecStatus.NORMAL, in_out, stderr), 'in.txt', 'out.txt')
            self.assertEqual(expected, result)

    def test_build_details_str__on_runtime_failure(self):
        in_out = 'correct\n'
        stderr = ''
        expected = (with_color('[Input]', Fore.LIGHTMAGENTA_EX) + '\n'
                    + in_out + with_color('[Expected]',
                                          Fore.LIGHTMAGENTA_EX) + '\n' + in_out
                    + with_color('[Received]',
                                 Fore.LIGHTMAGENTA_EX) + '\n' + in_out
                    + with_color('Aborted ({})\n'.format(ExecStatus.RE.name), Fore.LIGHTYELLOW_EX) + '\n')
        io_mock = mock_open(read_data=in_out)

        with patch('atcodertools.tools.tester.open', io_mock):
            result = build_details_str(ExecResult(
                ExecStatus.RE, in_out, stderr), 'in.txt', 'out.txt')
            self.assertEqual(expected, result)

    def test_compiler_and_tester(self):
        test_dir = os.path.join(self.temp_dir, "test1")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_compiler_and_tester"), test_dir)
        for i in [1, 2, 3, 4]:
            self.assertTrue(tester.main(
                '', ['-d', test_dir, "-n", "{:d}".format(i), "--compile-before-testing",
                     "-j", "normal",
                     "--compile-command", "g++ main.cpp -o main && touch compile{}".format(i)]))
        lst = os.listdir(test_dir)
        self.assertTrue("compile1" in lst)
        self.assertTrue("compile2" in lst)
        self.assertTrue("compile3" in lst)
        self.assertTrue("compile4" in lst)

        test_dir = os.path.join(self.temp_dir, "test2")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_compiler_and_tester"), test_dir)
        for i in [1, 2, 3, 4]:
            self.assertTrue(tester.main(
                '', ['-d', test_dir, "-n", "{:d}".format(i), "--compile-before-testing",
                     "--compile-only-when-diff-detected", "-j", "normal",
                     "--compile-command", "g++ main.cpp -o main && touch compile{}".format(i)]))
        lst = os.listdir(test_dir)
        self.assertTrue("compile1" in lst)
        self.assertTrue("compile2" not in lst)
        self.assertTrue("compile3" not in lst)
        self.assertTrue("compile4" not in lst)

        test_dir = os.path.join(self.temp_dir, "test3")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_compiler_and_tester"), test_dir)
        for i in [1, 2, 3, 4]:
            self.assertTrue(tester.main(
                '', ['-d', test_dir, "-n", "{:d}".format(i), "--compile-before-testing",
                     "--compile-only-when-diff-detected", "-j", "normal",
                     "--compile-command", "g++ main.cpp -o main && touch compile{}".format(i)]))
            os.chdir(test_dir)
            os.system('echo // >> main.cpp')
        lst = os.listdir(test_dir)
        self.assertTrue("compile1" in lst)
        self.assertTrue("compile2" in lst)
        self.assertTrue("compile3" in lst)
        self.assertTrue("compile4" in lst)

    def test_compiler_and_tester_for_each_lang(self):
        test_dir = os.path.join(self.temp_dir, "test")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_compiler_and_tester_for_each_lang"), test_dir)
        config_path = os.path.join(
            RESOURCE_DIR, "test_compiler_and_tester_for_each_lang", "config.toml")
        for lang in ALL_LANGUAGES:
            lang_dir = os.path.join(test_dir, lang.name)

            compile_main_and_judge_programs(
                lang, force_compile=True, cwd=lang_dir)
            for i in [1, 2, 3, 4]:
                self.assertTrue(tester.main(
                    '', ['-d', lang_dir, "-n", "{:d}".format(i), "--compile-before-testing", "-j", "normal",
                         "--config", config_path]))

    def test_compiler_when_compiler_command_is_specified_in_option_file(self):
        test_dir = os.path.join(self.temp_dir, "test")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_compiler_when_compiler_command_is_specified_in_option_file"), test_dir)
        config_path = os.path.join(
            RESOURCE_DIR, "test_compiler_when_compiler_command_is_specified_in_option_file", "tester_options.toml")
        f = io.StringIO()
        sys.stdout = f
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "--compile-before-testing",
                 "-j", "normal",
                 "--config", config_path]))
        sys.stdout = sys.__stdout__
        stdouts = f.getvalue().split("\n")
        self.assertTrue(
            True if "compile command:  g++ main.cpp -o main -std=c++17" in stdouts else False)

    def test_timeout(self):
        test_dir = os.path.join(self.temp_dir, "test_timeout")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_timeout"), test_dir)
        # main.cppは5秒間停止た後に正しい答えを返す
        # timeoutは5.252秒になっている
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "--compile-before-testing",
                 "-j", "normal",
                 "--compile-command", "g++ main.cpp -o main"]))
        self.assertFalse(tester.main(
            '', ['-d', test_dir, "--compile-before-testing",
                 "-j", "normal", "-t", "4",
                 "--compile-command", "g++ main.cpp -o main"]))
        self.assertTrue(tester.main(
            '', ['-d', test_dir, "--compile-before-testing",
                 "-j", "normal", "-t", "6",
                 "--compile-command", "g++ main.cpp -o main"]))
        config_path = os.path.join(test_dir, "config_timeout_adjustment.toml")
        self.assertFalse(tester.main(
            '', ['-d', test_dir, "--compile-before-testing",
                 "-j", "normal",
                 "--compile-command", "g++ main.cpp -o main",
                 "--config", config_path]))

    def test_timeout_fail(self):
        test_dir = os.path.join(self.temp_dir, "test_timeout_fail")
        shutil.copytree(os.path.join(
            RESOURCE_DIR, "test_timeout_fail"), test_dir)
        self.assertFalse(tester.main(
            '', ['-d', test_dir, "--compile-before-testing",
                 "-j", "normal",
                 "--compile-command", "g++ main.cpp -o main"]))


if __name__ == '__main__':
    unittest.main()
