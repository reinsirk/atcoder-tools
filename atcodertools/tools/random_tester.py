import os
import shutil
import tempfile
from pathlib import Path

from atcodertools.codegen.code_style_config import CodeStyleConfig
from atcodertools.codegen.models.code_gen_args import CodeGenArgs
from atcodertools.common.logging import logger
from atcodertools.config.random_test_config import source_language
from atcodertools.executils.run_interactive import run_interactive
from atcodertools.executils.run_program import ExecStatus, run_program
from atcodertools.fileutils.create_contest_file import create_code
from atcodertools.tools.compiler import _compile, BadStatusCodeException


def prepare_random_test_files(problem_dir, main_source, constants, config):
    """Keep user-written helpers intact when gen is run again."""
    main_style = config.code_style_config
    generator_lang = config.random_test_config.generator_language
    generator_style = config.generator_code_style_config
    if generator_style is None:
        generator_style = (main_style if main_style.lang == generator_lang
                           else CodeStyleConfig(lang=generator_lang.name))
    naive_path = Path(problem_dir) / main_style.lang.get_code_filename("naive")
    generator_path = Path(problem_dir) / config.random_test_config.generator_filename
    if not naive_path.exists():
        create_code(main_source, str(naive_path))
        logger.info("Saved naive source to {}".format(naive_path))
    if not generator_path.exists():
        template = Path(generator_style.template_file).read_text()
        source = generator_style.code_generator(CodeGenArgs(template, None, constants, generator_style))
        create_code(source, str(generator_path))
        logger.info("Saved generator source to {}".format(generator_path))
    for filename in (config.random_test_config.judge_filename, config.random_test_config.interactor_filename):
        if filename and not (Path(problem_dir) / filename).exists():
            language = source_language(filename)
            style = main_style if main_style.lang == language else CodeStyleConfig(lang=language.name)
            source = style.code_generator(CodeGenArgs(Path(style.template_file).read_text(), None, constants, style))
            create_code(source, str(Path(problem_dir) / filename))
            logger.info("Saved judge source to {}".format(filename))


def _run(command, input_path, timeout, cwd, args=None):
    result = run_program(command, str(input_path), timeout, args=args, current_working_dir=cwd)
    # TimeoutExpired can return bytes even with universal_newlines=True.
    for field in ("output", "stderr"):
        value = getattr(result, field)
        if isinstance(value, bytes):
            value = value.decode(errors="replace")
        setattr(result, field, value or "")
    return result


def _save_failure(cwd, input_path, results, case_number):
    root = Path(cwd) / "random-test-failures"
    root.mkdir(exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="case-{}-".format(case_number), dir=str(root)))
    shutil.copyfile(input_path, target / "input.txt")
    for name, result in results.items():
        (target / (name + ".txt")).write_text(result.output)
        (target / (name + ".stderr.txt")).write_text(result.stderr)
    (target / "status.txt").write_text("\n".join(
        "{}: {}".format(name, result.status.value) for name, result in results.items()) + "\n")
    print("Saved failing case to {}".format(target))
    print("[Input]\n{}".format(input_path.read_text()))
    for name, result in results.items():
        print("[{}: {}]\n{}".format(name, result.status.value, result.output))
        if result.has_stderr():
            print("[{} stderr]\n{}".format(name, result.stderr))


def run_random_tests(metadata, config, cwd, timeout, judge_method, main_command=None,
                     judge_command=None, interactor_command=None):
    """Compile each program once, then stop at the first discrepancy or execution failure."""
    cwd = os.path.abspath(cwd)
    random_config = config.random_test_config
    generator_lang = random_config.generator_language
    generator_name = Path(random_config.generator_filename).stem
    judge_source = random_config.judge_filename
    interactor_source = random_config.interactor_filename
    mode = random_config.mode
    if mode == "normal":
        judge_source = interactor_source = judge_command = interactor_command = None
    elif mode == "judge":
        interactor_source = interactor_command = None
        if not (judge_source or judge_command):
            logger.error("Judge mode requires judge_filename or --judge-exec")
            return False
    elif mode == "interactive":
        judge_source = judge_command = None
        if not (interactor_source or interactor_command):
            logger.error("Interactive mode requires interactor_filename or --interactor-exec")
            return False
    if mode == "auto" and not any((judge_source, interactor_source, judge_command, interactor_command)):
        if metadata.problem_type == "interactive":
            logger.error("Interactive problem detected: configure interactor_filename or --interactor-exec")
            return False
        if metadata.problem_type == "output_validation":
            logger.info("Multiple valid outputs detected; normal comparison selected. "
                        "Use judge_filename or --judge-exec to validate alternative outputs.")
    interactive = interactor_command is not None or interactor_source is not None
    if (judge_command or judge_source) and interactive:
        logger.error("Choose either an output judge or an interactor")
        return False
    programs = [(generator_name, generator_lang)]
    if not interactive:
        programs.insert(0, ("naive", metadata.lang))
    for filename, command in ((judge_source, judge_command), (interactor_source, interactor_command)):
        if filename and command is None:
            language = source_language(filename)
            programs.append((Path(filename).stem, language))
    if main_command is None:
        programs.insert(0, ("main", metadata.lang))
    for name, lang in programs:
        if not (Path(cwd) / lang.get_code_filename(name)).is_file():
            logger.error("Missing source: {}. Enable [random_test] enabled = true and run gen, "
                         "or create the file yourself.".format(lang.get_code_filename(name)))
            return False
    try:
        for name, lang in programs:
            print("[{} Program]".format(name))
            # The solution's custom compiler command also applies to same-language helpers.
            custom_command = config.tester_config.compile_command if lang == metadata.lang else None
            if name != "main" and custom_command and "{filename}" not in custom_command:
                logger.warning("Custom compile_command has no {{filename}}; using the default compiler for {}".format(name))
                custom_command = None
            _compile(lang.get_code_filename(name), lang.get_exec_filename(name),
                     lang.get_compile_command(name, custom_command), cwd,
                     not config.tester_config.compile_only_when_diff_detected)
    except (BadStatusCodeException, OSError) as error:
        logger.error("Random-test compilation failed: {}".format(error))
        return False

    main_command = main_command or metadata.lang.get_test_command("main")
    naive_command = metadata.lang.get_test_command("naive")
    generator_command = generator_lang.get_test_command(generator_name)
    if judge_source and judge_command is None:
        judge_command = source_language(judge_source).get_test_command(Path(judge_source).stem)
    if interactor_source and interactor_command is None:
        interactor_command = source_language(interactor_source).get_test_command(Path(interactor_source).stem)
    case_number = 0
    try:
        with tempfile.TemporaryDirectory(prefix="atcoder-random-test-") as working_dir:
            empty_path = Path(working_dir) / "empty.txt"
            empty_path.touch()
            input_path = Path(working_dir) / "input.txt"
            while random_config.iterations == 0 or case_number < random_config.iterations:
                case_number += 1
                generated = _run(generator_command, empty_path, timeout, cwd)
                input_path.write_text(generated.output)
                results = {"generator": generated}
                if generated.status != ExecStatus.NORMAL or not generated.output.strip():
                    print("# random case {} ... generator failed or produced empty input".format(case_number))
                    _save_failure(cwd, input_path, results, case_number)
                    return False
                if interactive:
                    actual, interaction = run_interactive(main_command, interactor_command, input_path, timeout, cwd)
                    results.update(main=actual, interactor=interaction)
                    correct = actual.status == ExecStatus.NORMAL and interaction.status == ExecStatus.NORMAL
                    status = "interactive failure"
                else:
                    correct, status = _compare_outputs(main_command, naive_command, judge_command,
                                                       input_path, empty_path, timeout, cwd, judge_method, results)
                if not correct:
                    print("# random case {} ... {}".format(case_number, status))
                    _save_failure(cwd, input_path, results, case_number)
                    return False
                if case_number % 100 == 0:
                    print("Passed {} random test cases".format(case_number), flush=True)
    except KeyboardInterrupt:
        print("Random testing interrupted after {} completed cases".format(case_number - 1))
        return False
    except OSError as error:
        logger.error("Unable to run random tests: {}".format(error))
        return False
    print("Passed all {} random test cases!".format(case_number))
    return True


def _compare_outputs(main_command, naive_command, judge_command, input_path, empty_path,
                     timeout, cwd, judge_method, results):
    expected = _run(naive_command, input_path, timeout, cwd)
    results["naive"] = expected
    if expected.status != ExecStatus.NORMAL:
        return False, "naive {}".format(expected.status.value)
    actual = _run(main_command, input_path, timeout, cwd)
    results["main"] = actual
    if actual.status != ExecStatus.NORMAL:
        return False, actual.status.value
    if judge_command:
        expected_path = input_path.parent / "naive.txt"
        actual_path = input_path.parent / "main.txt"
        expected_path.write_text(expected.output)
        actual_path.write_text(actual.output)
        judged = _run(judge_command, empty_path, timeout, cwd,
                      args=[str(input_path), str(expected_path), str(actual_path)])
        results["judge"] = judged
        return judged.status == ExecStatus.NORMAL, "judge rejected or failed ({})".format(judged.status.value)
    try:
        correct = actual.is_correct_output(expected.output, judge_method)
    except ValueError:
        # Non-numeric output is a wrong answer under a decimal judge.
        correct = False
    return correct, "WA"
