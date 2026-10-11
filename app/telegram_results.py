"""Attach confirmed YouTube links to the original, per-result Telegram message."""
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading

logger = logging.getLogger('telegram')


def youtube_link(markup, video_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(video_id or '')):
        return markup
    line = f'▶️ <a href="https://www.youtube.com/watch?v={video_id}">Assistir no YouTube</a>'
    heading, separator, rest = str(markup).partition('\n')
    return heading + '\n\n' + line + (separator + rest if separator else '')


class ResultNotifications:
    def __init__(self, delivery, root='/data/output/telegram-results'):
        self.delivery = delivery
        self.root = Path(root)
        self.lock = threading.RLock()

    def _path(self, video):
        identity = hashlib.sha256(str(Path(video).resolve()).encode()).hexdigest()
        return self.root / (identity + '.json')

    def _read(self, video):
        try:
            record = json.loads(self._path(video).read_text(encoding='utf-8'))
            return record if isinstance(record, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, video, record):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.result-', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False)
            os.replace(temporary, self._path(video))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _target(token, chat):
        return hashlib.sha256(str(token).encode()).hexdigest() + ':' + str(chat).strip()

    def _receipt(self, record, token, chat):
        target = self._target(token, chat)
        receipts = record.get('receipts', {})
        if target in receipts:
            return target, receipts[target]
        bot = target.partition(':')[0]
        for key, receipt in receipts.items():
            if key.partition(':')[0] == bot and str(receipt.get('chat_id')) == str(chat).strip():
                return key, receipt
        return target, None

    def _send(self, video, token, chat, markup, attachment=None, cancelled=None):
        with self.lock:
            video_id = self._read(video).get('youtube_id')
        decorated = youtube_link(markup, video_id)
        if attachment:
            result = self.delivery.send_video(token, chat, attachment, decorated, cancelled=cancelled)
        else:
            result = self.delivery.send_message(token, chat, decorated)
        if result.ok:
            reported_chat = result.data.get('chat')
            actual_chat = reported_chat.get('id', chat) if isinstance(reported_chat, dict) else chat
            target = self._target(token, chat)
            with self.lock:
                record = self._read(video)
                record.setdefault('receipts', {})[target] = {
                    'message_id': result.data['message_id'], 'video': bool(attachment),
                    'markup': markup, 'youtube_id': video_id, 'chat_id': str(actual_chat),
                }
                self._save(video, record)
            # Publication may have completed while this message was being sent.
            self._update(video, token, chat)
        return result

    def send_video(self, video, token, chat, attachment, caption, cancelled=None):
        return self._send(video, token, chat, caption, attachment, cancelled)

    def send_message(self, video, token, chat, message):
        return self._send(video, token, chat, message)

    def _update(self, video, token, chat):
        with self.lock:
            record = self._read(video)
            target, receipt = self._receipt(record, token, chat)
            video_id = record.get('youtube_id')
            if not receipt or not video_id or receipt.get('youtube_id') == video_id:
                return True
        actual_chat = receipt.get('chat_id', chat)
        result = self.delivery.edit_message(token, actual_chat, receipt['message_id'],
            youtube_link(receipt['markup'], video_id), video=receipt['video'])
        if result.ok:
            with self.lock:
                record = self._read(video)
                current = record.get('receipts', {}).get(target)
                if current and current['message_id'] == receipt['message_id']:
                    current['youtube_id'] = video_id
                    self._save(video, record)
            return True
        if result.kind == 'message_unavailable':
            return self._notify_once(video, token, actual_chat)
        return False

    def _notify_once(self, video, token, chat):
        target = self._target(token, chat)
        with self.lock:
            record = self._read(video)
            video_id = record.get('youtube_id')
            attempt = target + ':' + str(video_id)
            if attempt in record.get('announced', []):
                return True
            # A timeout can mean the message arrived. Never repeat this write blindly.
            record.setdefault('announced', []).append(attempt)
            self._save(video, record)
        message = youtube_link('✅ <b>Vídeo publicado no YouTube</b>\n\n🎵 <b>' +
            html.escape(str(record.get('title') or Path(video).stem)[:100]) + '</b>', video_id)
        result = self.delivery.send_message(token, chat, message)
        return result.ok or result.kind == 'network_error'

    def published(self, video, video_id, title, targets, automatic=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(video_id or '')):
            return False
        with self.lock:
            record = self._read(video)
            record.update(youtube_id=video_id, title=title)
            self._save(video, record)
        success = True
        for target in targets:
            token, chat = target['telegram_token'], target['telegram_chat_id']
            with self.lock:
                _, has_receipt = self._receipt(self._read(video), token, chat)
            if has_receipt:
                success = self._update(video, token, chat) and success
            elif not automatic:
                success = self._notify_once(video, token, chat) and success
        return success
