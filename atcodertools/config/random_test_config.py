import re
from pathlib import Path

from atcodertools.common.language import ALL_LANGUAGES
from atcodertools.fileutils.normalize import normalize_path


class RandomTestConfig:
    def __init__(self, enabled: bool = False, generator_filename: str = "generate.cpp", iterations: int = 1000,
                 judge_filename: str = None, interactor_filename: str = None,
                 naive_template_file: str = None, generator_template_file: str = None,
                 judge_template_file: str = None, interactor_template_file: str = None):
        if type(enabled) is not bool:
            raise ValueError("enabled must be true or false")
        self.enabled = enabled
        self.generator_language = source_language(generator_filename)
        if Path(generator_filename).stem in ("main", "naive", "judge", "interactor"):
            raise ValueError("generator_filename must differ from main, naive, judge and interactor")
        if type(iterations) is not int or iterations < 0:
            raise ValueError("iterations must be a non-negative integer (0 means unlimited)")
        self.generator_filename = generator_filename
        self.iterations = iterations
        names = {"main", "naive", Path(generator_filename).stem}
        for filename in (judge_filename if judge_filename is not None else "judge.cpp",
                         interactor_filename if interactor_filename is not None else "interactor.cpp"):
            source_language(filename)
            if Path(filename).stem in names:
                raise ValueError("Random-test program filenames must have different stems")
            names.add(Path(filename).stem)
        self.judge_filename = judge_filename
        self.interactor_filename = interactor_filename
        for name, path in (("naive_template_file", naive_template_file),
                           ("generator_template_file", generator_template_file),
                           ("judge_template_file", judge_template_file),
                           ("interactor_template_file", interactor_template_file)):
            if path is not None and (not isinstance(path, str) or not path):
                raise ValueError("{} must be a template file path".format(name))
            path = normalize_path(path)
            if path is not None and not Path(path).is_file():
                raise ValueError("{}: template file not found: {}".format(name, path))
            setattr(self, name, path)


def source_language(filename):
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9]+", filename):
        raise ValueError("Expected a source filename, e.g. generate.cpp")
    language = next((lang for lang in ALL_LANGUAGES if lang.extension == Path(filename).suffix[1:]), None)
    if language is None:
        raise ValueError("Unsupported source extension: {}".format(filename))
    return language
