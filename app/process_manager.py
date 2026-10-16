import threading
import subprocess

active_process = None
cancel_event = threading.Event()
process_kill_lock = threading.Lock()

def set_active_process(proc):
    with process_kill_lock:
        global active_process
        active_process = proc
    # A cancellation can arrive between check_cancelled() and Popen().
    if cancel_event.is_set():
        stop_process(proc)
        clear_active_process(proc)
        check_cancelled()

def clear_active_process(proc=None):
    with process_kill_lock:
        global active_process
        if proc is None or active_process is proc:
            active_process = None


def stop_process(proc, timeout=3):
    """Reap a child even when an output/progress callback raises an exception."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except (OSError, ProcessLookupError):
        # The cancellation route may have reaped the same process already.
        proc.wait()

def check_cancelled():
    if cancel_event.is_set():
        raise InterruptedError("Cancelado pelo usuário.")
