import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atcodertools.client.atcoder import AtCoderClient
from atcodertools.client.atcoder_problems import AtCoderProblemsError
from atcodertools.client.models.contest import Contest
from atcodertools.client.models.problem import Problem
from atcodertools.client.models.problem_content import ProblemContent
from atcodertools.client.models.sample import Sample
from atcodertools.codegen.code_style_config import CodeStyleConfig
from atcodertools.config.config import Config
from atcodertools.config.etc_config import EtcConfig
from atcodertools.config.postprocess_config import PostprocessConfig
from atcodertools.tools import envgen, get_default_config_path, tester
from atcodertools.tools.models.metadata import Metadata
from tests.test_atcoder_problems import (
    CONTEST_ID, CONTEST_URL, CONTEST_DATA, PROBLEM_DATA, json_response,
)


class TestVirtualContestEnvGen(unittest.TestCase):
    def setUp(self):
        temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_dir.cleanup)
        self.workspace = Path(temporary_dir.name)
        self.config = Config(
            code_style_config=CodeStyleConfig(
                workspace_dir=str(self.workspace), lang="python"),
            etc_config=EtcConfig(
                in_example_format="input_{}.txt", out_example_format="output_{}.txt"),
        )
        self.content = ProblemContent(
            "N\n", [Sample("3\n", "6\n")], original_html="<p>Time Limit: 2 sec</p>")

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_generate_samples_and_run_existing_tester(self, get):
        get.side_effect = [json_response(
            CONTEST_DATA), json_response(PROBLEM_DATA)]
        client = mock.Mock(spec=AtCoderClient)
        client.download_problem_content.return_value = self.content
        self.config.postprocess_config = PostprocessConfig(
            exec_on_each_problem_dir="touch problem-hook",
            exec_on_contest_dir="touch contest-hook",
        )
        envgen.prepare_contest(client, CONTEST_URL, self.config)
        client.download_problem_list.assert_not_called()
        contest_dir = self.workspace / CONTEST_ID
        self.assertEqual(sorted(os.listdir(contest_dir)),
                         ["A", "B", "C", "contest-hook"])
        self.assertFalse((self.workspace / "arc058").exists())
        for alphabet, source in zip(["A", "B", "C"], PROBLEM_DATA):
            problem_dir = contest_dir / alphabet
            self.assertEqual((problem_dir / "input_1.txt").read_text(), "3\n")
            self.assertEqual((problem_dir / "output_1.txt").read_text(), "6\n")
            self.assertTrue((problem_dir / "problem-hook").is_file())
            self.assertTrue((problem_dir / "main.py").is_file())
            metadata = Metadata.load_from(problem_dir / "metadata.json")
            self.assertEqual(metadata.problem.get_alphabet(),
                             source["problem_index"])
            self.assertEqual(
                metadata.problem.get_contest().get_id(), source["contest_id"])
            self.assertEqual(metadata.problem.problem_id, source["id"])
            self.assertEqual(metadata.sample_in_pattern, "input_*.txt")
            self.assertEqual(metadata.sample_out_pattern, "output_*.txt")
            (problem_dir / "main.py").write_text("print(int(input()) * 2)\n")
            command = shlex.quote(sys.executable) + " " + \
                shlex.quote(str(problem_dir / "main.py"))
            self.assertTrue(tester.main("", ["--dir", str(problem_dir), "--exec", command,
                                             "--config", get_default_config_path()]))
        requested_problems = [call.args[0]
                              for call in client.download_problem_content.call_args_list]
        self.assertEqual([p.problem_id for p in requested_problems], [
                         p["id"] for p in PROBLEM_DATA])

    @mock.patch("atcodertools.tools.envgen.AtCoderProblemsClient")
    def test_backup_and_skip_use_virtual_workspace(self, problems_client):
        problem = Problem(Contest("arc058"), "C", "arc058_a")
        problems_client.return_value.download_problem_list.return_value = [
            problem]
        client = mock.Mock(spec=AtCoderClient)
        client.download_problem_content.return_value = self.content
        envgen.prepare_contest(client, CONTEST_ID, self.config)
        code_path = self.workspace / CONTEST_ID / "A" / "main.py"
        code_path.write_text("my solution\n")
        self.config.etc_config.skip_existing_problems = True
        envgen.prepare_contest(client, CONTEST_ID, self.config)
        self.assertEqual(client.download_problem_content.call_count, 1)
        self.assertEqual(code_path.read_text(), "my solution\n")
        self.config.etc_config.skip_existing_problems = False
        envgen.prepare_contest(client, CONTEST_ID, self.config)
        self.assertEqual(
            Path(str(code_path) + ".1").read_text(), "my solution\n")

    @mock.patch("atcodertools.tools.envgen.prepare_procedure")
    @mock.patch("atcodertools.tools.envgen.AtCoderProblemsClient")
    def test_more_than_26_problems_have_distinct_directories(self, problems_client, prepare):
        problem = Problem(Contest("abc042"), "A", "abc042_a")
        problems_client.return_value.download_problem_list.return_value = [
            problem] * 28
        envgen.prepare_contest(
            mock.Mock(spec=AtCoderClient), CONTEST_ID, self.config)
        labels = [call.args[4] for call in prepare.call_args_list]
        self.assertEqual(labels[:3], ["A", "B", "C"])
        self.assertEqual(labels[25:], ["Z", "AA", "AB"])
        self.assertEqual(len(set(labels)), 28)

    @mock.patch("atcodertools.tools.envgen.Pool")
    @mock.patch("atcodertools.tools.envgen.AtCoderProblemsClient")
    def test_parallel_preparation_passes_virtual_paths(self, problems_client, pool):
        problem = Problem(Contest("arc058"), "C", "arc058_a")
        problems_client.return_value.download_problem_list.return_value = [
            problem]
        client = mock.Mock(spec=AtCoderClient)
        client.download_problem_content.return_value = self.content
        pool.return_value.map.side_effect = lambda func, tasks: [
            func(task) for task in tasks]
        self.config.etc_config.parallel_download = True
        envgen.prepare_contest(client, CONTEST_ID, self.config)
        metadata_path = self.workspace / CONTEST_ID / "A" / "metadata.json"
        self.assertTrue(metadata_path.is_file())

    @mock.patch("atcodertools.tools.envgen.AtCoderClient")
    @mock.patch("atcodertools.tools.envgen.AtCoderProblemsClient")
    def test_cli_accepts_url_and_id_without_login(self, problems_client, client_class):
        problem = Problem(Contest("arc058"), "C", "arc058_a")
        problems_client.return_value.download_problem_list.return_value = [
            problem]
        client_class.return_value.download_problem_content.return_value = self.content
        for contest in [CONTEST_URL, CONTEST_ID]:
            envgen.main("", [contest, "--without-login", "--lang", "python",
                             "--workspace", str(self.workspace), "--config", get_default_config_path()])
        client_class.return_value.login.assert_not_called()
        client_class.return_value.download_problem_list.assert_not_called()
        self.assertEqual(problems_client.return_value.download_problem_list.call_args_list,
                         [mock.call(CONTEST_ID), mock.call(CONTEST_ID)])

    @mock.patch("atcodertools.tools.envgen.AtCoderClient")
    def test_invalid_url_fails_before_login(self, client):
        with self.assertRaises(SystemExit) as ctx:
            envgen.main("", [CONTEST_URL.replace(CONTEST_ID, "invalid")])
        self.assertEqual(ctx.exception.code, 2)
        client.assert_not_called()

    @mock.patch("atcodertools.tools.envgen.AtCoderClient")
    @mock.patch("atcodertools.tools.envgen.AtCoderProblemsClient")
    @mock.patch("atcodertools.tools.envgen.time.sleep")
    def test_api_error_returns_failure_without_contest_retries(self, sleep, problems_client, client):
        problems_client.return_value.download_problem_list.side_effect = AtCoderProblemsError(
            "404 Not Found")
        with self.assertRaises(SystemExit) as ctx:
            envgen.main("", [CONTEST_ID, "--without-login", "--workspace", str(self.workspace),
                             "--config", get_default_config_path()])
        self.assertEqual(ctx.exception.code, 1)
        sleep.assert_not_called()
        self.assertEqual(os.listdir(self.workspace), [])

    def test_ordinary_contest_keeps_existing_directory_and_metadata(self):
        problem = Problem(Contest("arc058"), "C", "arc058_a")
        client = mock.Mock(spec=AtCoderClient)
        client.download_problem_list.return_value = [problem]
        client.download_problem_content.return_value = self.content
        envgen.prepare_contest(client, "arc058", self.config)
        metadata = Metadata.load_from(
            self.workspace / "arc058" / "C" / "metadata.json")
        self.assertEqual(metadata.problem.to_dict(), problem.to_dict())
