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


class TestInteractiveProblemContent(unittest.TestCase):
    def test_abc244_c_has_no_batch_input_or_samples(self):
        html = (RESOURCE_DIR / 'abc244_c.html').read_text()
        content = ProblemContent.from_html(html)

        self.assertEqual('', content.get_input_format())
        self.assertEqual([], content.get_input_format_blocks())
        self.assertEqual([], content.get_samples())
        self.assertIn('インタラクティブな問題', content.get_input_format_context())
        self.assertEqual(html, content.original_html)

    def test_interactive_declaration_in_statement_or_io_section(self):
        for heading in ['問題文', '入出力', '入力', '対話']:
            with self.subTest(heading=heading):
                content = ProblemContent.from_html(f'''
                    <div class="part"><section><h3>{heading}</h3>
                    <p>この問題は<strong>インタラクティブな問題</strong>です。</p>
                    <pre>N</pre></section></div>
                    <section><h3>入出力例</h3>
                    <table><tr><td><pre>2</pre></td><td></td></tr>
                    <tr><td></td><td><pre>1</pre></td></tr></table></section>
                ''')
                self.assertEqual('', content.get_input_format())
                self.assertEqual([], content.get_samples())

    def test_ordinary_problem_with_no_samples_still_requires_input_format(self):
        with self.assertRaises(InputFormatDetectionError):
            ProblemContent.from_html('''
                <section><h3>入力</h3><p>整数 N が与えられる。</p></section>
            ''')

        with self.assertRaises(SampleDetectionError):
            ProblemContent.from_html('''
                <section><h3>入力</h3><pre>N</pre></section>
                <section><h3>入力例 1</h3><pre>1</pre></section>
            ''')

    def test_interactive_text_in_sample_does_not_change_ordinary_parsing(self):
        content = ProblemContent.from_html('''
            <div class="part"><section><h3>問題文</h3>
            <p>文字列をそのまま出力してください。</p></section></div>
            <section><p>見出しのない補足。</p></section>
            <section><h3>入力</h3><pre>S</pre></section>
            <section><h3>入力例 1</h3><pre>インタラクティブな問題</pre></section>
            <section><h3>出力例 1</h3><pre>インタラクティブな問題</pre></section>
        ''')
        self.assertEqual('S\n', content.get_input_format())
        self.assertEqual(['S\n'], content.get_input_format_blocks())
        self.assertEqual(1, len(content.get_samples()))
        self.assertEqual('インタラクティブな問題\n', content.get_samples()[0].get_input())
        self.assertEqual(
            'インタラクティブな問題\n', content.get_samples()[0].get_output())

    def test_gen_creates_abc244_c_code_and_metadata(self):
        html = (RESOURCE_DIR / 'abc244_c.html').read_text()
        problem = Problem(Contest('abc244'), 'C', 'abc244_c')
        client = AtCoderClient()
        with tempfile.TemporaryDirectory() as workspace:
            config = Config(
                code_style_config=CodeStyleConfig(
                    workspace_dir=workspace,
                    lang='cpp',
                ),
                etc_config=EtcConfig(),
            )
            with mock.patch.object(client, '_request', return_value=mock.Mock(text=html)):
                prepare_procedure(client, problem, config)

            problem_dir = Path(workspace) / 'abc244' / 'C'
            self.assertEqual(
                ['main.cpp', 'metadata.json'],
                sorted(path.name for path in problem_dir.iterdir()),
            )
            code = (problem_dir / 'main.cpp').read_text()
            self.assertIn('int main()', code)
            self.assertNotIn('cin >>', code)
            metadata = Metadata.load_from(problem_dir / 'metadata.json')
            self.assertEqual(problem.to_dict(), metadata.problem.to_dict())
            self.assertEqual('main.cpp', metadata.code_filename)
            self.assertEqual(2000, metadata.timeout_ms)
