"""Save a standalone C++ source containing the user's local libraries."""
import argparse
import os
import sys

from atcodertools.common.library_expander import ExpansionError, expand_source_file, resolve_include_dirs
from atcodertools.common.logging import logger
from atcodertools.config.config import Config, ConfigType, USER_CONFIG_PATH
from atcodertools.tools import get_default_config_path
from atcodertools.tools.models.metadata import Metadata


def add_include_arguments(parser):
    parser.add_argument('--include-dir', '-I', dest='include_dirs', action='append', default=None,
                        help='Custom C++ library search directory; repeat to specify multiple paths')


def add_expansion_arguments(parser):
    add_include_arguments(parser)
    parser.add_argument('--expanded-filename', '--output', '-o', dest='expanded_filename', default=None,
                        help='Expanded output path relative to --dir [Default] <source>.expanded.cpp')


def expand_code(code_path, directory, config, lang):
    if lang != 'cpp':
        raise ExpansionError(
            'Library expansion currently supports only C++ (cpp)')
    include_dirs = resolve_include_dirs(directory, config.include_dirs)
    output_path = (os.path.join(directory, os.path.expanduser(config.expanded_filename))
                   if config.expanded_filename else None)
    return expand_source_file(code_path, include_dirs, output_path)


def main(prog, args):
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument('--dir', '-d', default='.',
                        help='Target problem directory [Default] Current directory')
    parser.add_argument('--code', '-c', default=None,
                        help='Source path relative to --dir [Default] metadata.json or main.cpp')
    parser.add_argument('--config', default=None,
                        help='Config file [Default] ~/.atcodertools.toml or bundled config')
    add_expansion_arguments(parser)
    args = parser.parse_args(args)
    try:
        metadata_path = os.path.join(args.dir, 'metadata.json')
        metadata = Metadata.load_from(
            metadata_path) if os.path.exists(metadata_path) else None
        lang = metadata.lang.name if metadata else 'cpp'
        config_path = args.config or (USER_CONFIG_PATH if os.path.exists(USER_CONFIG_PATH)
                                      else get_default_config_path())
        with open(config_path) as fp:
            config = Config.load(fp, {ConfigType.EXPAND}, args, lang)
        code_path = os.path.join(args.dir, os.path.expanduser(
            args.code or (metadata.code_filename if metadata else 'main.cpp')))
        output_path = expand_code(
            code_path, args.dir, config.expand_config, lang)
    except (ExpansionError, OSError, ValueError) as error:
        logger.error(str(error))
        return False
    logger.info('Expanded source saved to {}'.format(output_path))
    return True


if __name__ == '__main__':
    main(sys.argv[0], sys.argv[1:])
