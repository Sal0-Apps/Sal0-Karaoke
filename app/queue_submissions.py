"""Confirm queue submissions without repeating accepted work after a lost response."""
import re
import threading
import time
from functools import wraps


class SubmissionProgress:
    """Share preparation progress without waiting for the processing queue's lock."""
    def __init__(self):
        self.lock = threading.RLock()
        self.entries = {}

    def get(self, username, identifier):
        with self.lock:
            entry = self.entries.get((username, identifier))
            return dict(entry[1]) if entry else None

    def begin(self, username, identifier):
        key = (username, identifier)
        with self.lock:
            now = time.monotonic()
            self.entries = {key: entry for key, entry in self.entries.items()
                            if entry[1]['status'] == 'preparing' or now - entry[0] < 3600}
            previous = self.entries.get(key)
            if previous and previous[1]['status'] in {'preparing', 'queued'}:
                return dict(previous[1])
            self.entries[key] = (now, {'status': 'preparing', 'submission_id': identifier})
        return None

    def finish(self, username, identifier, result):
        with self.lock:
            self.entries[(username, identifier)] = (time.monotonic(), dict(result))


def track_preparation(function):
    """One preparation per authenticated submission, including after proxy timeouts."""
    progress = SubmissionProgress()

    @wraps(function)
    def wrapped(*args, **kwargs):
        identifier = kwargs.get('submission_id', '')
        username = (kwargs.get('current_user') or {}).get('username')
        if not username or not valid_id(identifier):
            return function(*args, **kwargs)
        previous = progress.begin(username, identifier)
        if previous:
            return previous
        try:
            result = function(*args, **kwargs)
        except Exception as error:
            status = getattr(error, 'status_code', 500)
            detail = getattr(error, 'detail', '') if status < 500 else ''
            progress.finish(username, identifier, {
                'status': 'rejected', 'http_status': status,
                'detail': detail if isinstance(detail, str) and detail else 'Não foi possível preparar a inclusão. Tente novamente.'})
            raise
        progress.finish(username, identifier, result)
        return result

    wrapped.submissions = progress
    return wrapped


class DuplicateSubmission(Exception):
    def __init__(self, receipt):
        super().__init__("Esta inclusão já foi confirmada.")
        self.receipt = receipt


def valid_id(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{16,80}", str(value)))


def receipt(jobs, username, submission_id):
    if not username or not submission_id:
        return None
    waiting = 0
    for job in jobs:
        if job.get("status") == "queued":
            waiting += 1
        if job.get("submission_id") == submission_id and job.get("submission_owner", job.get("owner_username")) == username:
            return {"status": "queued", "job_id": job["id"], "title": job.get("title"),
                    "position": waiting if job.get("status") == "queued" else None,
                    "job_status": job.get("status")}
    return None
