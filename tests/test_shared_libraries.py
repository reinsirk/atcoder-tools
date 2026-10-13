import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import toml

from atcodertools.common.language import CPP, PYTHON
from atcodertools.tools import compiler, expand, submit, tester


@unittest.skipUnless(shutil.which('g++'), 'g++ is required')
class TestSharedLibraries(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library = self.root / 'shared library'
        self.header = self.library / 'my' / 'math.hpp'
        self.header.parent.mkdir(parents=True)
        self.write_header(42)
        self.config = self.root / 'config.toml'
        self.config.write_text(toml.dumps({
            'expand': {'cpp': {'include_dirs': [str(self.library)]}},
            'compiler': {'compile_only_when_diff_detected': True},
            'tester': {'cpp': {'compile_before_testing': True, 'compile_only_when_diff_detected': True}},
        }), encoding='utf-8')
        self.problems = []
        for alphabet in ('A', 'B'):
            directory = self.root / 'workspace' / 'abc215' / alphabet
            directory.mkdir(parents=True)
            (directory / 'main.cpp').write_text(
                '#include <iostream>\n#include "my/math.hpp"\n'
                'int main() { std::cout << answer() << "\\n"; }\n', encoding='utf-8')
            (directory / 'metadata.json').write_text(json.dumps({
                'problem': {'contest': {'contest_id': 'abc215'},
                            'problem_id': 'abc215_' + alphabet.lower(), 'alphabet': alphabet},
                'code_filename': 'main.cpp', 'lang': 'cpp',
                'sample_in_pattern': 'in_*.txt', 'sample_out_pattern': 'out_*.txt',
            }), encoding='utf-8')
            (directory / 'in_1.txt').write_text('', encoding='utf-8')
            (directory / 'out_1.txt').write_text('42\n', encoding='utf-8')
            self.problems.append(directory)
        # Simulate setting the shared path once in ~/.atcodertools.toml.
        for tool in (compiler, expand, submit, tester):
            patcher = patch.object(tool, 'USER_CONFIG_PATH', str(self.config))
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_header(self, answer):
        self.header.write_text(
            '#pragma once\ninline int answer() { return ' + str(answer) + '; }\n', encoding='utf-8')

    def client(self):
        client = Mock()
        client.download_submission_list.return_value = []
        client.submit_source_code.return_value.submission_id = 123
        return client

    def test_one_shared_directory_works_in_multiple_problem_folders(self):
        for directory in self.problems:
            with self.subTest(directory=directory):
                self.assertTrue(tester.main('', ['--dir', str(directory)]))
                self.assertTrue(expand.main('', ['--dir', str(directory)]))
                output = directory / 'main.expanded.cpp'
                self.assertIn('return 42;', output.read_text())
                self.assertFalse((directory / 'my').exists())

    def test_submit_uses_same_config_for_compilation_and_automatic_expansion(self):
        directory = self.problems[0]
        client = self.client()
        self.assertTrue(submit.main(
            '', ['--dir', str(directory)], client=client))
        self.assertTrue((directory / 'main').exists())
        submitted = client.submit_source_code.call_args.args[3]
        self.assertIn('return 42;', submitted)
        self.assertNotIn('#include "my/math.hpp"', submitted)
        self.assertEqual(
            (directory / 'main.expanded.cpp').read_text(), submitted)

    def test_header_change_recompiles_even_with_diff_optimization(self):
        directory = self.problems[0]
        previous_directory = os.getcwd()
        try:
            os.chdir(directory)
            compiler.main('', [])
            source_mtime = (directory / 'main.cpp').stat().st_mtime_ns
            self.write_header(43)
            compiler.main('', [])
            source = directory / 'main.cpp'
            self.assertEqual(source_mtime, source.stat().st_mtime_ns)
            result = subprocess.run(
                [str(directory / 'main')], check=True, capture_output=True, text=True)
            self.assertEqual('43\n', result.stdout)
        finally:
            os.chdir(previous_directory)

    def test_submit_cli_include_dirs_and_config_reach_sample_compilation(self):
        empty_config = self.root / 'tester.toml'
        empty_config.write_text(
            '[tester.cpp]\ncompile_before_testing=true\n', encoding='utf-8')
        client = self.client()
        self.assertTrue(submit.main('', ['-d', str(self.problems[0]), '--config', str(empty_config),
                                         '-I', str(self.library)], client=client))
        self.assertIn(
            'return 42;', client.submit_source_code.call_args.args[3])

    def test_shell_compile_command_and_relative_library_path(self):
        directory = self.problems[0]
        relative_library = os.path.relpath(self.library, directory)
        compiler.compile_main_and_judge_programs(
            CPP, str(directory), compile_command='g++ main.cpp -o main -std=c++17 && touch compiled',
            include_dirs=[relative_library])
        self.assertTrue((directory / 'compiled').exists())
        self.assertEqual('42\n', subprocess.check_output(
            [str(directory / 'main')], text=True))


class TestCompilerLibraryEnvironment(unittest.TestCase):

    def test_compiler_environment_preserves_existing_paths_without_mutation(self):
        with patch.dict(os.environ, {'CPLUS_INCLUDE_PATH': '/existing/library'}), \
                patch('atcodertools.tools.compiler.run_command_with_returncode', return_value=(0, '')) as run:
            compiler.compile_main_and_judge_programs(
                CPP, '/tmp/problem', include_dirs=['../lib', '~/library'])
            env = run.call_args.kwargs['env']
            expected = [str(Path('/tmp/lib').resolve()), str(Path('~/library').expanduser().resolve()),
                        '/existing/library']
            self.assertEqual(os.pathsep.join(expected),
                             env['CPLUS_INCLUDE_PATH'])
            self.assertEqual('/existing/library',
                             os.environ['CPLUS_INCLUDE_PATH'])

    def test_other_languages_do_not_receive_cpp_search_paths(self):
        with patch('atcodertools.tools.compiler.run_command_with_returncode', return_value=(0, '')) as run:
            compiler.compile_main_and_judge_programs(
                PYTHON, force_compile=True, include_dirs=['/library'])
        self.assertIsNone(run.call_args.kwargs['env'])
