import io
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from atcodertools.client.models.contest import Contest
from atcodertools.client.models.problem import Problem
from atcodertools.codegen.code_style_config import CodeStyleConfig
from atcodertools.codegen.models.code_gen_args import CodeGenArgs
from atcodertools.common.judgetype import DecimalJudge, NormalJudge
from atcodertools.common.language import CPP, PYTHON
from atcodertools.config.config import Config, ConfigType
from atcodertools.config.random_test_config import RandomTestConfig
from atcodertools.config.tester_config import TesterConfig as CompilerTestConfig
from atcodertools.constprediction.models.problem_constant_set import ProblemConstantSet
from atcodertools.constprediction.problem_type_prediction import predict_problem_type
from atcodertools.executils.run_program import ExecResult, ExecStatus
from atcodertools.executils.run_interactive import run_interactive
from atcodertools.tools import envgen, tester
from atcodertools.tools.models.metadata import Metadata
from atcodertools.tools.random_tester import prepare_random_test_files, run_random_tests


class TestRandomTester(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="random tests ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.metadata = Metadata(Problem(Contest("abc001"), "A", "abc001_1"),
                                 "main.py", "in_*.txt", "out_*.txt", PYTHON)
        self.config = Config(random_test_config=RandomTestConfig(generator_filename="generate.py", iterations=3))
        self.write_python()

    def write_python(self, main="import sys; print(int(input()) * 2)", naive=None, generator="print(7)"):
        (self.root / "main.py").write_text(main)
        (self.root / "naive.py").write_text(naive or main)
        (self.root / "generate.py").write_text(generator)

    def run_tests(self, judge=None, main_command=None):
        with redirect_stdout(io.StringIO()) as output:
            passed = run_random_tests(self.metadata, self.config, str(self.root), 0.3,
                                      judge or NormalJudge(), main_command)
        return passed, output.getvalue()

    def failure(self):
        paths = list((self.root / "random-test-failures").glob("case-*"))
        self.assertEqual(len(paths), 1)
        return paths[0]

    def test_pass(self):
        passed, output = self.run_tests()
        self.assertTrue(passed)
        self.assertIn("Passed all 3 random test cases!", output)
        self.assertFalse((self.root / "random-test-failures").exists())

    def test_mismatch_saves_case_and_stops(self):
        self.write_python(main="print(15)", naive="print(14)")
        passed, output = self.run_tests()
        self.assertFalse(passed)
        self.assertIn("case 1 ... WA", output)
        failure = self.failure()
        self.assertEqual((failure / "input.txt").read_text(), "7\n")
        self.assertEqual((failure / "main.txt").read_text(), "15\n")
        self.assertEqual((failure / "naive.txt").read_text(), "14\n")
        # Running again must preserve the old counterexample.
        self.run_tests()
        self.assertEqual(len(list((self.root / "random-test-failures").iterdir())), 2)

    def test_generator_errors_and_empty_input(self):
        for source in ("raise RuntimeError('generator failed')", "pass", "import time; time.sleep(2)"):
            with self.subTest(source=source):
                self.write_python(generator=source)
                self.assertFalse(self.run_tests()[0])
        self.assertEqual(len(list((self.root / "random-test-failures").iterdir())), 3)

    def test_main_and_naive_failures(self):
        for name in ("main.py", "naive.py"):
            for source, status in (("raise RuntimeError('bad')", "RE"),
                                   ("import time; print('partial', flush=True); time.sleep(2)", "TLE")):
                with self.subTest(name=name, status=status):
                    self.write_python()
                    (self.root / name).write_text(source)
                    passed, output = self.run_tests()
                    self.assertFalse(passed)
                    self.assertIn(status, output)
        failures = list((self.root / "random-test-failures").iterdir())
        self.assertEqual(len(failures), 4)
        self.assertTrue(any("partial" in p.read_text() for d in failures for p in d.glob("*.txt")))

    def test_decimal_judge(self):
        self.write_python(main="print(1.005)", naive="print(1.0)")
        self.assertTrue(self.run_tests(DecimalJudge(diff=0.01))[0])
        self.write_python(main="print('not a number')", naive="print(1.0)")
        self.assertFalse(self.run_tests(DecimalJudge(diff=0.01))[0])

    def test_missing_source_and_compile_failure(self):
        (self.root / "naive.py").unlink()
        self.assertFalse(self.run_tests()[0])
        self.write_python(main="syntax error!")
        self.assertFalse(self.run_tests()[0])

    def test_exec_override_does_not_require_main_source(self):
        (self.root / "main.py").unlink()
        self.assertTrue(self.run_tests(main_command="python3 naive.py")[0])

    def test_unlimited_and_interrupt(self):
        self.config.random_test_config.iterations = 0
        with patch("atcodertools.tools.random_tester._run", side_effect=KeyboardInterrupt):
            passed, output = self.run_tests()
        self.assertFalse(passed)
        self.assertIn("interrupted", output)

    def test_progress(self):
        self.config.random_test_config.iterations = 100
        generated = ExecResult(ExecStatus.NORMAL, "7\n", "", 0)
        with patch("atcodertools.tools.random_tester._run", return_value=generated):
            passed, output = self.run_tests()
        self.assertTrue(passed)
        self.assertIn("Passed 100 random test cases", output)

    def test_unlaunchable_program(self):
        with patch("atcodertools.tools.random_tester._run", side_effect=FileNotFoundError("missing")):
            self.assertFalse(self.run_tests()[0])

    def test_cli_loads_config_and_iteration_override(self):
        self.metadata.save_to(str(self.root / "metadata.json"))
        config_path = self.root / "config.toml"
        config_path.write_text('[random_test]\ngenerator_filename="generate.py"\niterations=7\n')
        with redirect_stdout(io.StringIO()) as output:
            self.assertTrue(tester.main("", ["--random-test", "--dir", str(self.root),
                                             "--config", str(config_path), "--iterations", "2"]))
        self.assertIn("Passed all 2 random test cases!", output.getvalue())

    def test_invalid_cli_options(self):
        for args in (["--random-test", "--num", "1"], ["--iterations", "2"],
                     ["--random-test", "--iterations", "-1"]):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                tester.main("", args)

    def test_custom_judge_and_normal_mode(self):
        self.write_python(main="print(15)", naive="print(14)")
        self.config.random_test_config.judge_filename = "checker.py"
        (self.root / "checker.py").write_text(
            "import pathlib, sys\n"
            "assert len(sys.argv) == 4\n"
            "n, expected, actual = [int(pathlib.Path(p).read_text()) for p in sys.argv[1:]]\n"
            "sys.exit(0 if actual in (n*2, n*2+1) and expected == n*2 else 1)\n")
        self.metadata.problem_type = "output_validation"
        self.assertTrue(self.run_tests()[0])
        self.config.random_test_config.mode = "normal"
        self.assertFalse(self.run_tests()[0])

    def test_judge_rejection_and_timeout(self):
        self.config.random_test_config.judge_filename = "checker.py"
        (self.root / "checker.py").write_text("import sys; print('invalid'); sys.exit(1)")
        passed, output = self.run_tests()
        self.assertFalse(passed)
        self.assertIn("judge rejected", output)
        self.assertEqual((self.failure() / "judge.txt").read_text(), "invalid\n")
        (self.root / "checker.py").write_text("import time; time.sleep(2)")
        self.assertFalse(self.run_tests()[0])

    def test_non_unique_output_detection_allows_normal_comparison(self):
        self.metadata.problem_type = "output_validation"
        self.assertTrue(self.run_tests()[0])

    def write_interactive(self):
        self.config.random_test_config.interactor_filename = "interactor.py"
        self.metadata.problem_type = "interactive"
        (self.root / "naive.py").unlink()
        (self.root / "main.py").write_text(
            "limit = int(input())\nprint('? 0', flush=True)\n"
            "secret = int(input())\nprint('! ' + str(secret), flush=True)\n")
        (self.root / "interactor.py").write_text(
            "import pathlib, sys\nsecret = int(pathlib.Path(sys.argv[1]).read_text())\n"
            "print(100, flush=True)\nassert input() == '? 0'\nprint(secret, flush=True)\n"
            "assert input() == '! ' + str(secret)\n")

    def test_interactive_dialogue_without_naive(self):
        self.write_interactive()
        self.assertTrue(self.run_tests()[0])

    def test_interactive_failure_saves_transcript(self):
        self.write_interactive()
        (self.root / "main.py").write_text("input(); print('! 999', flush=True)")
        self.assertFalse(self.run_tests()[0])
        failure = self.failure()
        self.assertIn("! 999", (failure / "main.txt").read_text())
        self.assertEqual((failure / "interactor.txt").read_text(), "100\n")
        self.assertIn("AssertionError", (failure / "interactor.stderr.txt").read_text())

    def test_interactive_timeout(self):
        self.write_interactive()
        (self.root / "main.py").write_text("import time; time.sleep(2)")
        self.assertFalse(self.run_tests()[0])
        self.assertIn("TLE", (self.failure() / "status.txt").read_text())

    def test_interactive_launch_failure_and_missing_interactor(self):
        self.metadata.problem_type = "interactive"
        self.assertFalse(self.run_tests()[0])
        self.config.random_test_config.interactor_filename = "interactor.py"
        (self.root / "interactor.py").write_text("pass")
        with patch("atcodertools.tools.random_tester.run_interactive", side_effect=FileNotFoundError):
            self.assertFalse(self.run_tests()[0])

    def test_interactive_launch_failure_cleans_up_solver(self):
        launched = []
        original = subprocess.Popen

        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            launched.append(process)
            return process

        with patch("atcodertools.executils.run_interactive.subprocess.Popen", side_effect=launch):
            with self.assertRaises(FileNotFoundError):
                run_interactive("python3 main.py", "./missing-interactor", self.root / "generate.py", 0.3, str(self.root))
        self.assertEqual(len(launched), 1)
        self.assertIsNotNone(launched[0].returncode)
        for stream in (launched[0].stdin, launched[0].stdout, launched[0].stderr):
            self.assertTrue(stream.closed)

    def test_special_mode_validation(self):
        for mode in ("judge", "interactive"):
            with self.subTest(mode=mode):
                self.config.random_test_config.mode = mode
                self.assertFalse(self.run_tests()[0])

    def test_sample_custom_judge(self):
        (self.root / "in_1.txt").write_text("7\n")
        (self.root / "out_1.txt").write_text("13\n")
        (self.root / "checker.py").write_text(
            "import pathlib, sys\nn, expected, actual = [int(pathlib.Path(p).read_text()) for p in sys.argv[1:]]\n"
            "sys.exit(0 if abs(expected - actual) <= 1 else 1)\n")
        self.metadata.save_to(str(self.root / "metadata.json"))
        config_path = self.root / "config.toml"
        config_path.write_text("")
        args = ["--dir", str(self.root), "--config", str(config_path), "--exec", "python3 main.py"]
        with redirect_stdout(io.StringIO()):
            self.assertFalse(tester.main("", args))
            self.assertTrue(tester.main("", args + ["--judge-exec", "python3 checker.py"]))
            self.assertTrue(tester.main("", args + ["--judge-exec", "python3 checker.py", "--num", "1"]))
        (self.root / "checker.py").write_text("import sys; sys.exit(1)")
        with redirect_stdout(io.StringIO()):
            self.assertFalse(tester.main("", args + ["--judge-exec", "python3 checker.py"]))

    def test_sample_judge_is_excluded_from_solution_inference(self):
        for name in ("main.py", "checker.py"):
            (self.root / name).write_text("#!/usr/bin/python3\nprint(14)\n")
            (self.root / name).chmod(0o755)
        self.metadata.save_to(str(self.root / "metadata.json"))
        (self.root / "in_1.txt").write_text("7\n")
        (self.root / "out_1.txt").write_text("14\n")
        (self.root / "config.toml").write_text('[random_test]\ngenerator_filename="generate.py"\n')
        with patch("atcodertools.tools.tester.run_program", return_value=ExecResult(ExecStatus.NORMAL, "14\n", "", 0)) as run:
            with redirect_stdout(io.StringIO()):
                self.assertTrue(tester.main("", ["--dir", str(self.root), "--config", str(self.root / "config.toml"),
                                                 "--judge-exec", "./checker.py"]))
        self.assertEqual(run.call_args.args[0], str(self.root / "main.py"))

    @unittest.skipUnless(shutil.which("g++"), "g++ is required")
    def test_real_cpp_compilation_and_random_inputs(self):
        # Alternate inputs using a counter so agreement is checked on multiple values.
        (self.root / "generate.cpp").write_text(
            '#include <fstream>\n#include <iostream>\nint main(){int n=0; '
            'std::ifstream("counter.txt") >> n; std::ofstream("counter.txt") << n+1; '
            'std::cout << n << "\\n";}')
        source = '#include <iostream>\nint main(){int n; std::cin>>n; std::cout<<n*2<<"\\n";}'
        (self.root / "main.cpp").write_text(source)
        (self.root / "naive.cpp").write_text(source)
        self.metadata.lang = CPP
        self.config.random_test_config = RandomTestConfig(iterations=5)
        self.config.tester_config = CompilerTestConfig(compile_command="g++ {filename}.cpp -o {filename} -std=c++17")
        self.assertTrue(self.run_tests()[0])
        self.assertEqual((self.root / "counter.txt").read_text(), "5")
        (self.root / "main.cpp").write_text(source.replace("n*2", "n*3"))
        self.assertFalse(self.run_tests()[0])
        self.assertEqual((self.failure() / "input.txt").read_text(), "5\n")

    @unittest.skipUnless(shutil.which("g++"), "g++ is required")
    def test_real_cpp_output_judge_and_interactor(self):
        (self.root / "generate.cpp").write_text('#include <iostream>\nint main(){std::cout<<7<<"\\n";}')
        (self.root / "main.cpp").write_text('#include <iostream>\nint main(){std::cout<<8<<"\\n";}')
        (self.root / "naive.cpp").write_text('#include <iostream>\nint main(){std::cout<<7<<"\\n";}')
        (self.root / "checker.cpp").write_text(
            '#include <fstream>\nint main(int argc,char** argv){int n,e,a; '
            'std::ifstream(argv[1])>>n; std::ifstream(argv[2])>>e; std::ifstream(argv[3])>>a; '
            'return argc==4 && e==n && a==n+1 ? 0:1;}')
        self.metadata.lang = CPP
        self.config.random_test_config = RandomTestConfig(iterations=2, judge_filename="checker.cpp")
        self.assertTrue(self.run_tests()[0])
        (self.root / "main.cpp").write_text(
            '#include <iostream>\nint main(){int n; std::cin>>n; std::cout<<n*2<<std::endl;}')
        (self.root / "interactor.cpp").write_text(
            '#include <iostream>\n#include <fstream>\nint main(int argc,char** argv){int n,a; '
            'std::ifstream(argv[1])>>n; std::cout<<n<<std::endl; '
            'if(!(std::cin>>a))return 1; return a==n*2?0:1;}')
        (self.root / "naive.cpp").unlink()
        self.config.random_test_config = RandomTestConfig(iterations=2, interactor_filename="interactor.cpp")
        self.assertTrue(self.run_tests()[0])


class TestRandomTestGeneration(unittest.TestCase):
    def test_default_disabled_and_config_validation(self):
        self.assertFalse(Config().random_test_config.enabled)
        for values in ({"iterations": -1}, {"iterations": True}, {"enabled": "true"},
                       {"generator_filename": "../generate.cpp"}, {"generator_filename": "main.cpp"},
                       {"generator_filename": "naive.cpp"}, {"generator_filename": "generate.xyz"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                RandomTestConfig(**values)

    def test_special_config_validation(self):
        for values in ({"mode": "invalid"}, {"judge_filename": "main.cpp"},
                       {"interactor_filename": "../interactor.cpp"},
                       {"judge_filename": "judge.cpp", "interactor_filename": "interactor.cpp"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                RandomTestConfig(**values)

    def test_html_detection_and_old_metadata_compatibility(self):
        for html, expected in (
                ("<section><h3>問題文</h3><p>これはインタラクティブな問題です。</p></section>", "interactive"),
                ("<p>This is an interactive problem.</p>", "interactive"),
                ("<p>この問題はインタラクティブな問題ではありません。</p>", "batch"),
                ("<p>答えが複数ある場合は、どれを出力しても正解となる。</p>", "output_validation"),
                ("<p>If there are multiple valid answers, print any of them.</p>", "output_validation"),
                ("<p>複数のテストケースが与えられます。</p>", "batch"),
                ("<script>This is an interactive problem.</script><p>Nを出力せよ。</p>", "batch")):
            with self.subTest(html=html):
                self.assertEqual(predict_problem_type(html), expected)
        old = Metadata(Problem(Contest("abc001"), "A", "abc001_1"), "main.cpp", "in_*", "out_*", CPP).to_dict()
        self.assertNotIn("problem_type", old)
        self.assertEqual(Metadata.from_dict(old).problem_type, "batch")
        old["problem_type"] = "interactive"
        self.assertEqual(Metadata.from_dict(old).to_dict()["problem_type"], "interactive")

    def test_same_template_and_preserve_existing_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.cpp"
            template.write_text('// custom template\n{% if prediction_success %}{{input_part}}{% endif %}\nint main(){}')
            config = Config(code_style_config=CodeStyleConfig(template_file=str(template)),
                            random_test_config=RandomTestConfig(enabled=True))
            constants = ProblemConstantSet()
            main = "// rendered solution with input reader"
            prepare_random_test_files(directory, main, constants, config)
            self.assertEqual((root / "naive.cpp").read_text(), main)
            expected = config.code_style_config.code_generator(
                CodeGenArgs(template.read_text(), None, constants, config.code_style_config))
            self.assertEqual((root / "generate.cpp").read_text(), expected)
            for name in ("naive.cpp", "generate.cpp"):
                (root / name).write_text("user code")
            prepare_random_test_files(directory, "new main", constants, config)
            for name in ("naive.cpp", "generate.cpp"):
                self.assertEqual((root / name).read_text(), "user code")

    def test_language_specific_config(self):
        config = Config.load(io.StringIO(
            '[codestyle]\nlang="cpp"\n[random_test]\nenabled=true\n'
            'generator_filename="generator.py"\niterations=20\n'),
            {ConfigType.CODESTYLE, ConfigType.RANDOM_TEST})
        self.assertTrue(config.random_test_config.enabled)
        self.assertEqual(config.random_test_config.iterations, 20)
        self.assertEqual(config.generator_code_style_config.lang, PYTHON)
        with tempfile.TemporaryDirectory() as directory:
            prepare_random_test_files(directory, "solution", ProblemConstantSet(), config)
            self.assertTrue((Path(directory) / "naive.cpp").exists())
            self.assertTrue((Path(directory) / "generator.py").exists())

    def test_gen_creates_helpers_when_enabled(self):
        from atcodertools.fmtprediction.models.format_prediction_result import FormatPredictionResult
        with tempfile.TemporaryDirectory() as directory:
            config = Config(code_style_config=CodeStyleConfig(workspace_dir=directory),
                            random_test_config=RandomTestConfig(enabled=True))
            problem = Problem(Contest("abc001"), "A", "abc001_1")
            content = Mock(original_html="")
            content.get_samples.return_value = []
            client = Mock()
            client.download_problem_content.return_value = content
            with patch("atcodertools.tools.envgen.predict_format", return_value=FormatPredictionResult.empty_result()):
                envgen.prepare_procedure(client, problem, config)
            root = Path(directory) / "abc001" / "A"
            self.assertEqual((root / "main.cpp").read_text(), (root / "naive.cpp").read_text())
            self.assertTrue((root / "generate.cpp").exists())
            self.assertTrue((root / "metadata.json").exists())
