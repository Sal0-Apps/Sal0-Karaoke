"""Confirm queue submissions without repeating accepted work after a lost response."""
import re


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
