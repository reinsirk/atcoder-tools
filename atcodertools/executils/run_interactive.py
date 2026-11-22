import subprocess
import threading
import time

from atcodertools.executils.run_program import ExecResult, ExecStatus


def run_interactive(main_command, interactor_command, input_path, timeout, cwd):
    """Interactor receives the case path in argv[1]; both programs exchange data over stdio."""
    processes = []
    threads = []
    streams = [bytearray() for _ in range(4)]

    def relay(source, destination, transcript):
        try:
            while True:
                chunk = source.read(4096)
                if not chunk:
                    break
                transcript.extend(chunk)
                if destination is not None:
                    try:
                        view = memoryview(chunk)
                        while view:
                            written = destination.write(view)
                            view = view[written:]
                    except (BrokenPipeError, OSError):
                        destination.close()
                        destination = None
        finally:
            source.close()
            if destination is not None:
                destination.close()

    start = time.monotonic()
    timed_out = False
    try:
        main = subprocess.Popen(main_command.split(" "), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, bufsize=0)
        processes.append(main)
        interactor = subprocess.Popen(interactor_command.split(" ") + [str(input_path)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, bufsize=0)
        processes.append(interactor)
        channels = ((main.stdout, interactor.stdin), (interactor.stdout, main.stdin),
                    (main.stderr, None), (interactor.stderr, None))
        for index, (source, destination) in enumerate(channels):
            thread = threading.Thread(target=relay, args=(source, destination, streams[index]), daemon=True)
            threads.append(thread)
            thread.start()
        while any(process.poll() is None for process in processes):
            if any(process.poll() not in (None, 0) for process in processes):
                break
            if time.monotonic() - start >= timeout:
                timed_out = True
                break
            time.sleep(0.01)
    finally:
        running = [process.poll() is None for process in processes]
        for process in processes:
            if process.poll() is None:
                process.kill()
        for process in processes:
            process.wait()
        for thread in threads:
            thread.join(timeout=1)
        # Covers launch failures before the relay threads were started.
        for process in processes:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()
    results = []
    for index, process in enumerate(processes):
        status = (ExecStatus.TLE if timed_out and running[index] else
                  ExecStatus.NORMAL if process.returncode == 0 else ExecStatus.RE)
        results.append(ExecResult(status, streams[index].decode(errors="replace"),
                                  streams[index + 2].decode(errors="replace"),
                                  elapsed_sec=time.monotonic() - start))
    return tuple(results)
