import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atcodertools.client.atcoder import AtCoderClient
from atcodertools.client.models.contest import Contest
from atcodertools.client.models.problem import Problem
from atcodertools.client.models.problem_content import (
    InputFormatDetectionError,
    ProblemContent,
    SampleDetectionError,
)
from atcodertools.codegen.code_style_config import CodeStyleConfig
from atcodertools.config.config import Config
from atcodertools.config.etc_config import EtcConfig
from atcodertools.tools.envgen import prepare_procedure
from atcodertools.tools.models.metadata import Metadata


RESOURCE_DIR = Path(__file__).parent / 'resources' / 'test_problem_content'


class TestNonBatchProblemContent(unittest.TestCase):
    def test_arc226_interactive_and_output_only_statements(self):
        for alphabet, marker in [('d', 'インタラクティブ'), ('e', '入力は与えられない')]:
            with self.subTest(problem=alphabet):
                html = (RESOURCE_DIR / f'arc226_{alphabet}.html').read_text()
                content = ProblemContent.from_html(html)

                self.assertEqual('', content.get_input_format())
                self.assertEqual([], content.get_input_format_blocks())
                self.assertEqual([], content.get_samples())
                self.assertIn(marker, content.get_input_format_context())
                self.assertEqual(html, content.original_html)

    def test_no_input_declaration_with_polite_wording(self):
        content = ProblemContent.from_html('''
            <section><h3>入力</h3>
            <p>この問題では入力は与えられません。</p></section>
        ''')
        self.assertEqual('', content.get_input_format())
        self.assertEqual([], content.get_samples())

    def test_malformed_ordinary_statement_still_raises(self):
        with self.assertRaises(InputFormatDetectionError):
            ProblemContent.from_html('''
                <section><h3>入力</h3><p>標準入力から与えられる。</p></section>
            ''')

        with self.assertRaises(SampleDetectionError):
            ProblemContent.from_html('''
                <section><h3>入力</h3><pre>N</pre></section>
                <section><h3>入力例 1</h3><pre>1</pre></section>
            ''')

    def test_ordinary_samples_are_preserved(self):
        content = ProblemContent.from_html('''
            <div class="part"><section><h3>問題文</h3>
            <p>整数を読み込み、そのまま出力してください。</p></section></div>
            <section><p>見出しのない補足。</p></section>
            <section><h3>入力</h3><pre>N</pre></section>
            <section><h3>入力例 1</h3><pre>1</pre></section>
            <section><h3>出力例 1</h3><pre>1</pre></section>
        ''')
        self.assertEqual('N\n', content.get_input_format())
        self.assertEqual(['N\n'], content.get_input_format_blocks())
        self.assertEqual(1, len(content.get_samples()))
        self.assertEqual('1\n', content.get_samples()[0].get_input())
        self.assertEqual('1\n', content.get_samples()[0].get_output())

    def test_gen_creates_code_and_metadata_without_samples(self):
        client = AtCoderClient()
        with tempfile.TemporaryDirectory() as workspace:
            config = Config(
                code_style_config=CodeStyleConfig(
                    workspace_dir=workspace,
                    lang='cpp',
                ),
                etc_config=EtcConfig(),
            )
            for alphabet in ['d', 'e']:
                with self.subTest(problem=alphabet):
                    html = (
                        RESOURCE_DIR / f'arc226_{alphabet}.html'
                    ).read_text()
                    problem = Problem(Contest('arc226'),
                                      alphabet.upper(), f'arc226_{alphabet}')
                    with mock.patch.object(client, '_request', return_value=mock.Mock(text=html)):
                        prepare_procedure(client, problem, config)

                    problem_dir = Path(workspace) / 'arc226' / alphabet.upper()
                    self.assertEqual(
                        ['main.cpp', 'metadata.json'],
                        sorted(path.name for path in problem_dir.iterdir()),
                    )
                    code = (problem_dir / 'main.cpp').read_text()
                    self.assertIn('int main()', code)
                    self.assertNotIn('cin >>', code)
                    metadata = Metadata.load_from(
                        problem_dir / 'metadata.json')
                    self.assertEqual(problem.to_dict(),
                                     metadata.problem.to_dict())
                    self.assertEqual('main.cpp', metadata.code_filename)
                    self.assertEqual(2000, metadata.timeout_ms)
