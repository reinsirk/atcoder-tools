import re
from pathlib import Path

from atcodertools.common.language import ALL_LANGUAGES


class RandomTestConfig:
    def __init__(self, enabled: bool = False, generator_filename: str = "generate.cpp", iterations: int = 1000,
                 judge_filename: str = None, interactor_filename: str = None, mode: str = "auto"):
        if type(enabled) is not bool:
            raise ValueError("enabled must be true or false")
        self.enabled = enabled
        if mode not in ("auto", "normal", "judge", "interactive"):
            raise ValueError("mode must be auto, normal, judge or interactive")
        self.mode = mode
        self.generator_language = source_language(generator_filename)
        if Path(generator_filename).stem in ("main", "naive", "judge"):
            raise ValueError("generator_filename must differ from main, naive and judge")
        if type(iterations) is not int or iterations < 0:
            raise ValueError("iterations must be a non-negative integer (0 means unlimited)")
        self.generator_filename = generator_filename
        self.iterations = iterations
        if judge_filename and interactor_filename:
            raise ValueError("Choose either judge_filename or interactor_filename")
        names = {"main", "naive", Path(generator_filename).stem}
        for filename in (judge_filename, interactor_filename):
            if filename is not None:
                source_language(filename)
                if Path(filename).stem in names:
                    raise ValueError("Random-test program filenames must have different stems")
        self.judge_filename = judge_filename
        self.interactor_filename = interactor_filename


def source_language(filename):
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9]+", filename):
        raise ValueError("Expected a source filename, e.g. generate.cpp")
    language = next((lang for lang in ALL_LANGUAGES if lang.extension == Path(filename).suffix[1:]), None)
    if language is None:
        raise ValueError("Unsupported source extension: {}".format(filename))
    return language
