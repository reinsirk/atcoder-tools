import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atcodertools.common.library_expander import ExpansionError, LibraryExpander, expand_source_file


class TestLibraryExpander(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
        return path

    def test_nested_includes_and_standard_headers(self):
        source = self.write(
            'main.cpp', '#include <vector>\n#include "lib/a.hpp"\nint main() {}\n')
        self.write('lib/a.hpp', '#include "b.hpp"\nint a;\n')
        self.write('lib/b.hpp', 'int b;')
        result = LibraryExpander().expand(source)
        self.assertIn('#include <vector>', result)
        self.assertNotIn('#include "', result)
        self.assertLess(result.index('int b;'), result.index('int a;'))

    def test_angle_includes_only_search_explicit_directories(self):
        source = self.write(
            'main.cpp', '#include <custom/a.hpp>\n#include <vector>\n')
        self.write('custom/a.hpp', 'int should_stay_external;\n')
        self.write('library/custom/a.hpp', 'int custom;\n')
        self.assertEqual(source.read_text(), LibraryExpander().expand(source))
        result = LibraryExpander([self.root / 'library']).expand(source)
        self.assertIn('int custom;', result)
        self.assertIn('#include <vector>', result)
        self.assertNotIn('should_stay_external', result)

    def test_quote_search_order_and_include_directory_order(self):
        source = self.write('main.cpp', '#include "a.hpp"\n#include "b.hpp"\n')
        self.write('a.hpp', 'int local;\n')
        self.write('first/a.hpp', 'int other;\n')
        self.write('first/b.hpp', 'int first;\n')
        self.write('second/b.hpp', 'int second;\n')
        result = LibraryExpander(
            [self.root / 'first', self.root / 'second']).expand(source)
        self.assertIn('int local;', result)
        self.assertIn('int first;', result)
        self.assertNotIn('int other;', result)
        self.assertNotIn('int second;', result)

    def test_missing_local_header_fails_without_overwriting_output(self):
        source = self.write('main.cpp', '#include "missing.hpp"\n')
        output = self.write('main.expanded.cpp', 'old output\n')
        with self.assertRaisesRegex(ExpansionError, 'missing.hpp'):
            expand_source_file(source)
        self.assertEqual('old output\n', output.read_text())

    def test_rejects_overwriting_source_or_included_header(self):
        source = self.write('main.cpp', '#include "a.hpp"\n')
        header = self.write('a.hpp', 'int a;\n')
        for output in [source, header]:
            with self.subTest(output=output):
                with self.assertRaisesRegex(ExpansionError, 'overwrite'):
                    expand_source_file(source, output_path=output)
        self.assertEqual('int a;\n', header.read_text())

    def test_comments_raw_strings_and_macro_includes_are_preserved(self):
        text = ('// #include "missing.hpp"\n'
                '/*\n#include "missing.hpp"\n*/\n'
                'const char *text = R"tag(\n#include "missing.hpp"\n)tag";\n'
                '#define HEADER "missing.hpp"\n#include HEADER\n'
                '// comment continued \\\n#include "missing.hpp"\n')
        source = self.write('main.cpp', text)
        self.assertEqual(text, LibraryExpander().expand(source))

    def test_directive_spacing_continuations_and_surrounding_comments(self):
        source = self.write(
            'main.cpp', '/* before */ # include \\\n"a.hpp" /* after\ncomment */\n')
        self.write('a.hpp', 'int a;\n')
        result = LibraryExpander().expand(source)
        self.assertIn('int a;', result)
        self.assertIn('/* before */', result)
        self.assertIn('/* after\ncomment */', result)
        self.assertNotIn('# include', result)

    def test_raw_string_keeps_backslash_newline_and_embedded_include_text(self):
        text = 'const char *s = R"(text )\\\n"\n#include "missing.hpp"\n)";\nint main() {}\n'
        source = self.write('main.cpp', text)
        self.assertEqual(text, LibraryExpander().expand(source))

    @unittest.skipUnless(shutil.which('g++'), 'g++ is required')
    def test_multiline_comments_between_include_and_pragma_tokens(self):
        source = self.write(
            'main.cpp', '# /* first\ncomment */ include /* second\ncomment */ "a.hpp"\n'
            '#include "a.hpp"\nint main() { return a; }\n')
        self.write(
            'a.hpp', '# /* hash\ncomment */ pragma /* pragma\ncomment */ once\nint a;\n')
        result = LibraryExpander().expand(source)
        self.assertIn('int a;', result)
        self.assertNotIn('"a.hpp"', result)
        self.assertNotIn('pragma', result.replace('/* pragma\ncomment */', ''))
        self.assertIn('/* hash\ncomment */', result)
        self.assertIn('/* pragma\ncomment */', result)
        output = expand_source_file(source)
        (self.root / 'a.hpp').unlink()
        executable = self.root / 'program'
        subprocess.run(['g++', output, '-o', str(executable)],
                       check=True, capture_output=True)

    def test_unguarded_headers_are_repeated(self):
        source = self.write('main.cpp', '#include "a.hpp"\n#include "a.hpp"\n')
        self.write('a.hpp', 'ENTRY(item)\n')
        self.assertEqual(2, LibraryExpander().expand(
            source).count('ENTRY(item)'))

    def test_comments_between_directive_tokens(self):
        source = self.write(
            'main.cpp', '# /* first */ include /* second */ "a.hpp"\n')
        self.write('a.hpp', 'int a;\n')
        self.assertIn('int a;', LibraryExpander().expand(source))
        self.assertNotIn('# /* first */ include',
                         LibraryExpander().expand(source))

    def test_trailing_continuation_and_empty_source_are_preserved(self):
        for text in ('', '\\\n', 'int a;\n\\\n'):
            with self.subTest(text=text):
                source = self.write('main.cpp', text)
                self.assertEqual(text, LibraryExpander().expand(source))

    def test_invalid_encoding_and_missing_source(self):
        source = self.write('main.cpp', '')
        source.write_bytes(b'\x81')
        with self.assertRaisesRegex(ExpansionError, 'Cannot decode'):
            expand_source_file(source)
        with self.assertRaises(FileNotFoundError):
            expand_source_file(self.root / 'missing.cpp')

    def test_failed_output_replace_cleans_up_temporary_file(self):
        source = self.write('main.cpp', 'int main() {}\n')
        output = self.write('submission.cpp', 'old source\n')
        before = set(self.root.iterdir())
        with patch('atcodertools.common.library_expander.os.replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                expand_source_file(source, output_path=output)
        self.assertEqual(before, set(self.root.iterdir()))
        self.assertEqual('old source\n', output.read_text())

    def test_guarded_cycles_and_unguarded_cycles(self):
        source = self.write('main.cpp', '#include "a.hpp"\n')
        self.write(
            'a.hpp', '#ifndef A_HPP\n#define A_HPP\n#include "b.hpp"\nint a;\n#endif\n')
        self.write('b.hpp', '#include "a.hpp"\nint b;\n')
        self.assertIn('int b;', LibraryExpander().expand(source))
        self.write('a.hpp', '#include "b.hpp"\n')
        with self.assertRaisesRegex(ExpansionError, 'Circular include'):
            LibraryExpander().expand(source)

    def test_cp932_and_utf8_bom_are_decoded_to_utf8(self):
        source = self.write('main.cpp', '#include "a.hpp"\n')
        source.write_text(source.read_text(), encoding='utf-8-sig')
        header = self.root / 'a.hpp'
        header.write_bytes('// 日本語\n'.encode('cp932'))
        output = Path(expand_source_file(source))
        self.assertIn('// 日本語', output.read_text(encoding='utf-8'))
        self.assertFalse(output.read_bytes().startswith(b'\xef\xbb\xbf'))

    @unittest.skipUnless(shutil.which('g++'), 'g++ is required')
    def test_symlinked_header_uses_the_include_location_for_relative_headers(self):
        source = self.write(
            'main.cpp', '#include "alias.hpp"\nint main() { return answer(); }\n')
        header = self.write('real/a.hpp', '#pragma once\n#include "b.hpp"\n')
        self.write('b.hpp', 'int answer() { return 1; }\n')
        self.write('real/b.hpp', 'int answer() { return 2; }\n')
        (self.root / 'alias.hpp').symlink_to(header)
        for code in (source, Path(expand_source_file(source))):
            executable = self.root / 'program'
            subprocess.run(['g++', str(code), '-o', str(executable)],
                           check=True, capture_output=True)
            self.assertEqual(1, subprocess.run([str(executable)]).returncode)

    @unittest.skipUnless(shutil.which('g++'), 'g++ is required')
    def test_symlinked_source_keeps_its_include_location_and_output_directory(self):
        original = self.write(
            'real/main.cpp', '#include "b.hpp"\nint main() { return answer(); }\n')
        self.write('b.hpp', 'int answer() { return 1; }\n')
        self.write('real/b.hpp', 'int answer() { return 2; }\n')
        source = self.root / 'main.cpp'
        source.symlink_to(original)
        output = Path(expand_source_file(source))
        self.assertEqual(self.root / 'main.expanded.cpp', output)
        executable = self.root / 'program'
        subprocess.run(['g++', str(output), '-o', str(executable)],
                       check=True, capture_output=True)
        self.assertEqual(1, subprocess.run([str(executable)]).returncode)

    @unittest.skipUnless(shutil.which('g++'), 'g++ is required')
    def test_conditional_pragma_once_preserves_repeated_include_behavior(self):
        source = self.write('main.cpp', '#define ONCE 0\n#define ENTRY(name) int name;\n'
                            '#include "entries.hpp"\n#undef ENTRY\n'
                            '#define ENTRY(name) int other_##name;\n#include "entries.hpp"\n'
                            '#undef ENTRY\nint main() { return item + other_item; }\n')
        self.write('entries.hpp',
                   '#if ONCE\n#pragma once\n#endif\nENTRY(item)\n')
        output = expand_source_file(source)
        result = subprocess.run(['g++', '-std=c++17', output, '-o', str(self.root / 'program')],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(shutil.which('g++'), 'g++ is required')
    def test_expanded_program_compiles_with_conditional_once_and_cycles(self):
        source = self.write('main.cpp', '#include <iostream>\n'
                            '#if 0\n#include "a.hpp"\n#endif\n'
                            '#include "a.hpp"\n#include "alias.hpp"\n'
                            'int main() { std::cout << value() << "\\n"; }\n')
        self.write('a.hpp', '/* lead */ #pragma once /* trailing\ncomment */\n'
                   '#include "b.hpp"\ninline int value() { return helper(); }\n')
        self.write(
            'b.hpp', '#pragma once\n#include "a.hpp"\ninline int helper() { return 42; }\n')
        (self.root / 'alias.hpp').symlink_to(self.root / 'a.hpp')
        output = expand_source_file(source)
        expanded = Path(output).read_text()
        self.assertNotIn('#pragma once', expanded)
        self.assertNotIn('#include "', expanded)
        # Remove the headers so compilation proves the source is self-contained.
        for name in ('alias.hpp', 'a.hpp', 'b.hpp'):
            (self.root / name).unlink()
        executable = self.root / 'program'
        subprocess.run(['g++', '-std=c++17', output, '-o',
                       str(executable)], check=True, capture_output=True)
        result = subprocess.run(
            [str(executable)], check=True, capture_output=True, text=True)
        self.assertEqual('42\n', result.stdout)
