import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from atcodertools.config.config import Config, ConfigType
from atcodertools.tools import expand, submit


class TestExpandCommand(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'config.toml'
        self.config.write_text('', encoding='utf-8')
        self.source = self.root / 'solution.cpp'
        self.source.write_text(
            '#include "custom.hpp"\nint main() { return answer(); }\n', encoding='utf-8')
        (self.root / 'custom.hpp').write_text(
            '#pragma once\nint answer() { return 0; }\n', encoding='utf-8')
        self.metadata = {
            'problem': {'contest': {'contest_id': 'abc215'}, 'problem_id': 'abc215_a', 'alphabet': 'A'},
            'code_filename': 'solution.cpp', 'lang': 'cpp',
            'sample_in_pattern': 'in_*.txt', 'sample_out_pattern': 'out_*.txt',
        }
        self.save_metadata()
        self.args = ['--dir', str(self.root), '--config', str(self.config)]
        self.client = Mock()
        self.client.download_submission_list.return_value = []
        self.client.submit_source_code.return_value.submission_id = 123

    def save_metadata(self):
        (self.root / 'metadata.json').write_text(json.dumps(self.metadata), encoding='utf-8')

    def submitted_source(self):
        return self.client.submit_source_code.call_args.args[3]

    def test_expand_metadata_source_and_default_output(self):
        self.assertTrue(expand.main('', self.args))
        output = self.root / 'solution.expanded.cpp'
        self.assertIn('int answer()', output.read_text())
        self.assertIn('#include "custom.hpp"', self.source.read_text())

    def test_no_metadata_defaults_to_main_cpp_and_explicit_code(self):
        (self.root / 'metadata.json').unlink()
        (self.root / 'main.cpp').write_text(self.source.read_text(), encoding='utf-8')
        self.assertTrue(expand.main('', self.args))
        self.assertTrue((self.root / 'main.expanded.cpp').exists())
        self.assertTrue(expand.main(
            '', self.args + ['-c', 'solution.cpp', '-o', 'submit.cpp']))
        self.assertTrue((self.root / 'submit.cpp').exists())

    def test_include_paths_and_output_config_with_cli_override(self):
        (self.root / 'lib').mkdir()
        (self.root / 'lib/custom.hpp').write_text('int configured;\n', encoding='utf-8')
        self.source.write_text('#include <custom.hpp>\n', encoding='utf-8')
        self.config.write_text(
            '[expand.cpp]\ninclude_dirs=["lib"]\nexpanded_filename="configured.cpp"\n', encoding='utf-8')
        self.assertTrue(expand.main('', self.args))
        configured = self.root / 'configured.cpp'
        self.assertIn('int configured;', configured.read_text())
        self.assertTrue(expand.main(
            '', self.args + ['-I', '.', '-o', 'override.cpp']))
        self.assertIn('int answer()', (self.root / 'override.cpp').read_text())

    def test_expand_failure(self):
        (self.root / 'custom.hpp').unlink()
        self.assertFalse(expand.main('', self.args))
        self.assertFalse((self.root / 'solution.expanded.cpp').exists())

    def test_invalid_config(self):
        self.config.write_text(
            '[expand]\ninclude_dirs="lib"\n', encoding='utf-8')
        self.assertFalse(expand.main('', self.args))

    def test_missing_source_and_output_directory_fail(self):
        self.assertFalse(expand.main('', self.args + ['-c', 'missing.cpp']))
        self.assertFalse(expand.main(
            '', self.args + ['-o', 'missing/submission.cpp']))

    def test_invalid_output_filename_is_reported_before_submission(self):
        for value in ('123', 'false', '""', '"   "'):
            with self.subTest(value=value):
                self.config.write_text(
                    '[expand.cpp]\nexpanded_filename=' + value + '\n', encoding='utf-8')
                self.assertFalse(expand.main('', self.args))
                self.assertFalse(submit.main(
                    '', self.args + ['-f'], client=self.client))
                self.client.submit_source_code.assert_not_called()

    def test_repeated_include_directory_options_and_submit_output_override(self):
        (self.root / 'lib').mkdir()
        (self.root / 'lib/other.hpp').write_text('int other;\n', encoding='utf-8')
        self.source.write_text(
            '#include <custom.hpp>\n#include <other.hpp>\n', encoding='utf-8')
        args = self.args + ['-f', '-I',
                            '.', '-I', 'lib', '-o', 'combined.cpp']
        self.assertTrue(submit.main('', args, client=self.client))
        self.assertIn('int answer()', self.submitted_source())
        self.assertIn('int other;', self.submitted_source())
        self.assertEqual(self.submitted_source(),
                         (self.root / 'combined.cpp').read_text())

    def test_top_level_expand_dispatch(self):
        from atcodertools import atcoder_tools
        with patch.object(atcoder_tools, 'notify_if_latest_version_found'), \
                patch('sys.argv', ['atcoder-tools', 'expand'] + self.args):
            with self.assertRaises(SystemExit) as result:
                atcoder_tools.main()
        self.assertEqual(0, result.exception.code)
        self.assertTrue((self.root / 'solution.expanded.cpp').exists())

    def test_standalone_expansion_rejects_non_cpp_but_submission_is_unchanged(self):
        self.metadata['lang'] = 'python'
        self.save_metadata()
        self.assertFalse(expand.main('', self.args))
        self.assertTrue(submit.main(
            '', self.args + ['-f'], client=self.client))
        self.assertEqual(self.source.read_text(), self.submitted_source())
        self.assertFalse((self.root / 'solution.expanded.cpp').exists())

    def test_submit_expands_and_refreshes_stale_output(self):
        (self.root / 'solution.expanded.cpp').write_text('stale source', encoding='utf-8')
        self.assertTrue(submit.main(
            '', self.args + ['-f'], client=self.client))
        self.assertIn('int answer()', self.submitted_source())
        self.assertNotIn('#include "', self.submitted_source())
        self.assertEqual(self.submitted_source(),
                         (self.root / 'solution.expanded.cpp').read_text())
        header = self.root / 'custom.hpp'
        header.write_text('int answer() { return 1; }\n', encoding='utf-8')
        self.assertTrue(submit.main(
            '', self.args + ['-f'], client=self.client))
        self.assertIn('return 1;', self.submitted_source())
        self.assertNotIn('return 0;', self.submitted_source())

    def test_submit_output_filename_config(self):
        self.config.write_text(
            '[expand.cpp]\nexpanded_filename="submit.cpp"\n', encoding='utf-8')
        self.assertTrue(submit.main(
            '', self.args + ['-f'], client=self.client))
        self.assertEqual(self.submitted_source(),
                         (self.root / 'submit.cpp').read_text())

    def test_expansion_failure_prevents_submission_even_with_force(self):
        (self.root / 'custom.hpp').unlink()
        self.assertFalse(submit.main(
            '', self.args + ['-f'], client=self.client))
        self.client.submit_source_code.assert_not_called()

    def test_submission_safety_and_test_failure(self):
        self.client.download_submission_list.return_value = [
            Mock(problem_id='abc215_a')]
        self.assertFalse(submit.main(
            '', self.args + ['-f'], client=self.client))
        self.client.submit_source_code.assert_not_called()
        with patch('atcodertools.tools.submit.tester.main', return_value=False):
            submit.main('', self.args, client=self.client)
        self.client.submit_source_code.assert_not_called()

    def test_relative_problem_directory_is_not_joined_twice(self):
        relative_dir = os.path.relpath(self.root)
        args = ['--dir', relative_dir, '--config', str(self.config), '-f']
        self.assertTrue(submit.main('', args, client=self.client))
        self.assertIn('int answer()', self.submitted_source())
        self.assertNotIn('#include "', self.submitted_source())

    def test_absolute_code_path(self):
        self.assertTrue(submit.main(
            '', self.args + ['-f', '-c', str(self.source)], client=self.client))
        self.assertIn('int answer()', self.submitted_source())

    def test_expansion_runs_after_existing_hook(self):
        self.config.write_text(
            '[submit.cpp]\nexec_before_submit="generate"\nsubmit_filename="hook.cpp"\n', encoding='utf-8')

        def generate(command, directory):
            self.assertEqual('generate', command)
            hook_path = Path(directory) / 'hook.cpp'
            hook_path.write_text(self.source.read_text(), encoding='utf-8')

        with patch('atcodertools.tools.submit.run_command', side_effect=generate):
            self.assertTrue(submit.main(
                '', self.args + ['-f'], client=self.client))
        self.assertIn('int answer()', self.submitted_source())
        self.assertTrue((self.root / 'hook.expanded.cpp').exists())

    def test_language_specific_config_inherits_common_options(self):
        config = Config.load(io.StringIO('[expand]\ninclude_dirs=["lib"]\n'
                                         '[expand.cpp]\nexpanded_filename="submission.cpp"\n'),
                             {ConfigType.EXPAND, ConfigType.SUBMIT}, lang='cpp')
        self.assertEqual(['lib'], config.expand_config.include_dirs)
        self.assertEqual('submission.cpp',
                         config.expand_config.expanded_filename)
