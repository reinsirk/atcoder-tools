"""Inline literal C++ includes while leaving preprocessing conditions intact."""
import hashlib
from bisect import bisect_left
import os
from pathlib import Path
import re
import tempfile


class ExpansionError(Exception):
    pass


def resolve_include_dirs(directory, include_dirs):
    return [str((Path(directory) / Path(path).expanduser()).resolve()) for path in include_dirs]


# Mask literals too: an apparent directive inside a raw string is just data.
_TOKEN = re.compile(
    r'//[^\n]*|/\*[\s\S]*?(?:\*/|\Z)|'
    r'R"(?P<delimiter>[^\s()\\]{0,16})\([\s\S]*?\)(?P=delimiter)"|'
    r'"(?:\\[\s\S]|[^"\\])*"|(?<![\w])\'(?:\\[\s\S]|[^\'\\])*\'')
_INCLUDE = re.compile(r'^\s*#\s*include\b')
_HEADER = re.compile(r'(?:\s|/\*[\s\S]*?\*/)*(?:"([^"\n]+)"|<([^>\n]+)>)')
_PRAGMA_ONCE = re.compile(
    r'^\s*(?P<hash>#)\s*(?P<pragma>pragma)\s+(?P<once>once)\s*$')
_GUARD = re.compile(r'\A\s*#\s*ifndef\s+(\w+)\s*\n\s*#\s*define\s+\1\b')


def read_source(path):
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            return Path(path).read_text(encoding=encoding)
        except UnicodeDecodeError:
            pass
    raise ExpansionError('Cannot decode source file: {}'.format(path))


def _mask(source):
    # Track original offsets because raw strings retain backslash-newline pairs.
    positions = []
    chunks = []
    previous = 0
    for splice in re.finditer(r'\\\n', source):
        chunks.append(source[previous:splice.start()])
        positions.extend(range(previous, splice.start()))
        previous = splice.end()
    chunks.append(source[previous:])
    positions.extend(range(previous, len(source)))
    logical = ''.join(chunks)
    output = []
    offset = 0
    while True:
        token = _TOKEN.search(logical, offset)
        if token is None:
            output.append(logical[offset:])
            break
        end = token.end()
        delimiter = token.group('delimiter')
        if delimiter is not None:
            body_start = positions[token.start() + 2 + len(delimiter)] + 1
            terminator = ')' + delimiter + '"'
            original_end = source.find(terminator, body_start)
            end = (bisect_left(positions, original_end + len(terminator))
                   if original_end >= 0 else len(logical))
        output.append(logical[offset:token.start()])
        text = logical[token.start():end]
        # A block comment is one whitespace token, even when it spans lines.
        output.append(' ' * len(text) if text.startswith('/*') else
                      re.sub(r'[^\n]', ' ', text))
        offset = end
    return ''.join(output)


def _logical_lines(source):
    """Keep original text for output, but splice continuations for parsing."""
    pending = ''
    for line in source.splitlines(keepends=True):
        pending += line
        if line.endswith('\\\n'):
            continue
        yield pending, pending.replace('\\\n', '')
        pending = ''
    if pending:
        yield pending, pending.replace('\\\n', '')


def _parsed_lines(source):
    masked = _mask(source)
    offset = 0
    original_pending = logical_pending = mask_pending = ''
    for original, logical in _logical_lines(source):
        mask = masked[offset:offset + len(logical)]
        offset += len(logical)
        original_pending += original
        logical_pending += logical
        mask_pending += mask
        if mask.endswith('\n'):
            yield original_pending, logical_pending, mask_pending
            original_pending = logical_pending = mask_pending = ''
    if original_pending:
        yield original_pending, logical_pending, mask_pending


class LibraryExpander:

    def __init__(self, include_dirs=()):
        self.include_dirs = [Path(path).expanduser().resolve()
                             for path in include_dirs]
        self.input_paths = set()

    def expand(self, source_path):
        self.input_paths = set()
        return self._expand(Path(source_path).expanduser().absolute(), [], header=False)

    def _resolve(self, name, quoted, parent):
        directories = ([parent] if quoted else []) + self.include_dirs
        for directory in directories:
            path = directory / name
            if path.is_file():
                return path
        if quoted:
            raise ExpansionError(
                'Local header "{}" was not found (included from {})'.format(name, parent))
        # Angle includes outside the explicit search directories belong to the judge.
        return None

    def _expand(self, path, active, header=True):
        # Recognize aliases by identity while preserving the include location for searches.
        identity = path.resolve()
        self.input_paths.add(identity)
        source = read_source(path)
        lines = list(_parsed_lines(source))
        masked = ''.join(mask for _, _, mask in lines)
        once = any(_PRAGMA_ONCE.fullmatch(mask) for _, _, mask in lines)
        guard = 'ATCODER_TOOLS_EXPANDED_' + \
            hashlib.sha256(str(identity).encode()).hexdigest().upper()
        if identity in active:
            if once or _GUARD.match(masked):
                return '\n'
            raise ExpansionError('Circular include without a header guard: {}'.format(
                ' -> '.join(str(item) for item in active + [path])))
        output = []
        for original, logical, mask in lines:
            directive = _INCLUDE.match(mask)
            pragma = _PRAGMA_ONCE.fullmatch(mask)
            if header and pragma:
                # Keep trailing comments, including multiline block comments.
                definition = '#define {}'.format(guard)
                hash_start, hash_end = pragma.span('hash')
                pragma_start, pragma_end = pragma.span('pragma')
                once_start, once_end = pragma.span('once')
                original = (logical[:hash_start] + definition
                            + logical[hash_end:pragma_start]
                            + logical[pragma_end:once_start]
                            + logical[once_end:])
            elif directive:
                match = _HEADER.match(logical, directive.end())
                if match and not mask[match.end():].strip():
                    quoted = match.group(1) is not None
                    name = match.group(1) if quoted else match.group(2)
                    included = self._resolve(name, quoted, path.parent)
                    if included is not None:
                        content = self._expand(included, active + [identity])
                        # Preserve surrounding comments when replacing the directive.
                        original = (logical[:mask.index('#')]
                                    + content + '\n' + logical[match.end():])
            output.append(original)
        result = ''.join(output)
        if header and once:
            # Define the guard at each original pragma so its condition is preserved.
            result = '#ifndef {0}\n{1}\n#endif\n'.format(
                guard, result)
        return result


def expand_source_file(code_path, include_dirs=(), output_path=None):
    code_path = Path(code_path).expanduser().absolute()
    output_path = (Path(output_path).expanduser().absolute() if output_path else
                   code_path.with_name(code_path.stem + '.expanded' + code_path.suffix))
    expander = LibraryExpander(include_dirs)
    source = expander.expand(code_path)
    if output_path.resolve() in expander.input_paths:
        raise ExpansionError(
            'Expanded output must not overwrite a source or header: {}'.format(output_path))
    # A failed expansion must not truncate an earlier output file.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output_path.parent,
                                         delete=False) as output:
            temporary_path = output.name
            output.write(source)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return str(output_path)
