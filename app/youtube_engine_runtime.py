"""Transactional yt-dlp replacement; disposable package cleanup is best effort."""

import errno
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path


class EngineRuntime:
    def __init__(self, runtime, staging, backup):
        self.runtime = Path(runtime)
        self.staging = Path(staging)
        self.backup = Path(backup)
        self.discard_prefix = self.runtime.name + '.discarded-'
        self.logger = logging.getLogger(__name__)

    def recover(self):
        """Recover a server interrupted after moving the working package aside."""
        if not self.runtime.exists() and self.backup.is_dir():
            os.replace(self.backup, self.runtime)

    def prepare(self):
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        self.cleanup_obsolete()
        # An old installation directory cannot block or contaminate a retry.
        return tempfile.mkdtemp(prefix=self.staging.name + '-', dir=self.staging.parent)

    def discard(self, path):
        target = self.runtime.parent / (self.discard_prefix + uuid.uuid4().hex)
        os.replace(path, target)
        return target

    def activate(self, staging, reload_engine):
        """Called under the download/import locks. Rollback uses renames only."""
        self.recover()
        if self.backup.exists():
            self.discard(self.backup)
        had_previous = self.runtime.exists()
        if had_previous:
            os.replace(self.runtime, self.backup)
        installed = False
        try:
            os.replace(staging, self.runtime)
            installed = True
            result = reload_engine()
        except Exception:
            if installed:
                self.discard(self.runtime)
            if had_previous:
                os.replace(self.backup, self.runtime)
            try:
                reload_engine()
            except Exception:
                self.logger.exception('Falha ao recarregar o mecanismo restaurado.')
            raise
        # Retirement is housekeeping; a validated engine remains a success.
        if had_previous:
            try:
                self.discard(self.backup)
            except OSError as exc:
                self.logger.warning('Versão anterior mantida para limpeza posterior: %s', exc)
        return result

    def cleanup(self, path):
        """Retry a concurrently changing directory, leaving persistent failures for later."""
        for attempt in range(3):
            try:
                if os.path.islink(path):
                    os.unlink(path)
                else:
                    shutil.rmtree(path)
                return True
            except FileNotFoundError:
                if not os.path.lexists(path):
                    return True
            except OSError as exc:
                if exc.errno != errno.ENOTEMPTY or attempt == 2:
                    self.logger.warning('Limpeza de pacote adiada; mecanismo preservado: %s', exc)
                    return False
        self.logger.warning('Limpeza de pacote adiada: %s', path)
        return False

    def cleanup_obsolete(self):
        # Only known disposable package directories, never cookies or user files.
        self.cleanup(self.staging)
        try:
            for entry in self.runtime.parent.iterdir():
                if entry.name.startswith((self.discard_prefix, self.staging.name + '-')):
                    self.cleanup(entry)
        except OSError as exc:
            self.logger.warning('Limpeza de pacotes antigos adiada: %s', exc)
