import threading

active_process = None
cancel_event = threading.Event()
process_kill_lock = threading.Lock()

def set_active_process(proc):
    with process_kill_lock:
        global active_process
        active_process = proc

def clear_active_process():
    with process_kill_lock:
        global active_process
        active_process = None

def check_cancelled():
    if cancel_event.is_set():
        raise InterruptedError("Cancelado pelo usuário.")
