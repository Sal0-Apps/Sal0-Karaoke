"""Ordered bot delivery, safe formatting and actionable, credential-free status."""
from concurrent.futures import Future
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
from queue import Queue
import threading
import time
from urllib.parse import urlsplit

import requests

logger = logging.getLogger("telegram")


def units(text):
    return len(text.encode("utf-16-le")) // 2


class _Markup(HTMLParser):
    """Use entities instead of asking Telegram to parse generated HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = ""
        self.entities = []
        self.stack = []

    def handle_data(self, data):
        self.text += data

    def handle_starttag(self, tag, attrs):
        kinds = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic",
                 "u": "underline", "s": "strikethrough", "code": "code", "pre": "pre"}
        kind = kinds.get(tag)
        extra = {}
        if tag == "a":
            url = dict(attrs).get("href", "")
            try:
                valid_url = urlsplit(url).scheme in {"http", "https"}
            except ValueError:
                valid_url = False
            if valid_url:
                kind, extra = "text_link", {"url": url}
        if tag == "br":
            self.text += "\n"
        if kind:
            self.stack.append((tag, units(self.text), kind, extra))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            return
        _, offset, kind, extra = self.stack.pop()
        length = units(self.text) - offset
        if length:
            self.entities.append(dict(type=kind, offset=offset, length=length, **extra))


def formatted_parts(markup, limit):
    """Split at complete Unicode characters and keep links/bold valid in every part."""
    parser = _Markup()
    parser.feed(str(markup or ""))
    parser.close()
    text = parser.text
    offset = 0
    while text:
        end, size = 0, 0
        for char in text:
            size += units(char)
            if size > limit:
                break
            end += 1
        if end < len(text):
            newline = text.rfind("\n", 0, end + 1)
            if newline > end // 2:
                end = newline + 1
        part = text[:end]
        width = units(part)
        entities = []
        for entity in parser.entities:
            start = max(offset, entity["offset"])
            stop = min(offset + width, entity["offset"] + entity["length"])
            if stop > start:
                entities.append({**entity, "offset": start - offset, "length": stop - start})
        yield part, entities
        text, offset = text[end:], offset + width


@dataclass
class Result:
    ok: bool
    kind: str
    detail: str
    data: dict = field(default_factory=dict, repr=False)

    def public(self):
        return {"ok": self.ok, "kind": self.kind, "detail": self.detail}


class _Lane:
    def __init__(self, token, chat):
        self.token, self.chat = token, chat
        self.queue = Queue()
        self.next_send = 0
        self.state = {"state": "unverified", "detail": "Configuração salva. Verifique a conexão ou envie uma mensagem de teste."}


class TelegramDelivery:
    def __init__(self, on_migrate=None, post=None, clock=None, sleep=None):
        self.on_migrate = on_migrate
        self.post = post or requests.post
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.lock = threading.RLock()
        self.lanes = {}

    @staticmethod
    def key(token, chat):
        return sha256(str(token).encode()).hexdigest(), str(chat).strip()

    def _lane(self, token, chat):
        key = self.key(token, chat)
        with self.lock:
            if key not in self.lanes:
                lane = self.lanes[key] = _Lane(token, str(chat).strip())
                threading.Thread(target=self._work, args=(lane,), daemon=True).start()
            return self.lanes[key]

    def _work(self, lane):
        while True:
            future, operation = lane.queue.get()
            error = None
            try:
                result = operation(lane)
            except InterruptedError as exc:
                error = exc
            except Exception:
                result = Result(False, "internal_error", "Não foi possível concluir o envio. Tente novamente; o resultado continua na Biblioteca.")
                self._record(lane, result, "delivery")
            finally:
                lane.queue.task_done()
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

    def _submit(self, token, chat, operation):
        future = Future()
        if not token or not chat:
            future.set_result(Result(False, "unconfigured", "Informe o token do bot e o Chat ID em Ajustes → Telegram."))
        else:
            self._lane(token, chat).queue.put((future, operation))
        return future

    def status(self, token, chat):
        if not token or not chat:
            return {"state": "unconfigured", "detail": "Configure o bot e o Chat ID para receber mensagens.", "pending": 0}
        lane = self._lane(token, chat)
        with self.lock:
            return {**lane.state, "pending": lane.queue.unfinished_tasks}

    def _record(self, lane, result, method):
        with self.lock:
            lane.state.update(state="verified" if result.ok else result.kind, detail=result.detail, checked_at=time.time())
            if method.startswith("send"):
                lane.state["last_delivery"] = {**result.public(), "method": method, "at": time.time()}
            if method == "sendVideo":
                lane.state["last_video_delivery"] = {**result.public(), "at": time.time()}
            if result.ok and method.startswith("send"):
                lane.state["last_success_at"] = time.time()
        if not result.ok:
            logger.warning("Telegram: %s (%s).", method, result.kind)

    @staticmethod
    def _error(data, http):
        code = data.get("error_code", http)
        description = str(data.get("description", "")).lower()
        if code in {401, 404}:
            return Result(False, "invalid_token", "O token do bot não é válido ou foi revogado. Gere um novo no BotFather e salve aqui.")
        if code == 429:
            return Result(False, "rate_limited", "O Telegram pediu uma pausa nos envios. Aguarde e tente novamente.")
        if code == 403:
            return Result(False, "permission_denied", "O bot está bloqueado ou sem permissão neste destino. Inicie a conversa com ele ou permita mensagens e vídeos no grupo/canal.")
        if "chat not found" in description or "chat_id" in description:
            return Result(False, "chat_not_found", "O bot não encontra este Chat ID. Confira o número completo, adicione o bot ao grupo ou inicie a conversa com ele.")
        if "thread" in description or "topic" in description:
            return Result(False, "topic_required", "Este destino exige um tópico. Escolha um chat ou grupo em que o bot possa enviar sem tópico.")
        if http >= 500:
            return Result(False, "service_unavailable", "O serviço do Telegram está indisponível. Tente novamente mais tarde.")
        return Result(False, "rejected", "O Telegram recusou o envio. Confira o destino e as permissões para mensagens e vídeos.")

    def _wait(self, seconds, cancelled=None):
        while seconds > 0:
            if cancelled:
                cancelled()
            step = min(seconds, 1)
            self.sleep(step)
            seconds -= step

    def _request(self, lane, method, payload=None, video=None, cancelled=None, reading=False):
        waited = 0
        result = Result(False, "invalid_response", "O Telegram não retornou uma confirmação válida. Verifique a conexão do servidor e tente novamente.")
        for attempt in range(4 if not reading else 2):
            if cancelled:
                cancelled()
            if not reading:
                self._wait(max(0, lane.next_send - self.clock()), cancelled)
            body = dict(payload or {})
            if method != "getMe":
                body["chat_id"] = lane.chat
            try:
                url = f"https://api.telegram.org/bot{lane.token}/{method}"
                if video:
                    with open(video, "rb") as handle:
                        form = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in body.items()}
                        response = self.post(url, data=form, files={"video": (Path(video).name, handle, "video/mp4")}, timeout=(15, 300))
                else:
                    response = self.post(url, json=body, timeout=(10, 30))
                try:
                    data = response.json()
                except ValueError:
                    data = None
                if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
                    result = Result(False, "invalid_response", "O Telegram não retornou uma confirmação válida. Verifique a conexão do servidor e tente novamente.")
                    if reading and attempt == 0:
                        continue
                    return result
                if data["ok"]:
                    answer = data.get("result")
                    required = "message_id" if method.startswith("send") else "id" if method in {"getMe", "getChat"} else "status"
                    valid = isinstance(answer, dict)
                    if valid and required in {"id", "message_id"}:
                        valid = isinstance(answer.get(required), int) and not isinstance(answer[required], bool)
                    elif valid:
                        valid = answer.get("status") in {"creator", "administrator", "member", "restricted", "left", "kicked"}
                    if valid and method == "getMe":
                        valid = answer.get("is_bot") is True
                    if valid and method == "getChat":
                        valid = answer.get("type") in {"private", "group", "supergroup", "channel"} and isinstance(answer.get("permissions", {}), dict)
                    if valid:
                        return Result(True, "delivered" if not reading else "verified", "Mensagem confirmada pelo Telegram." if not reading else "Bot e destino verificados.", answer)
                    return result
                result = self._error(data, response.status_code)
                params = data.get("parameters")
                params = params if isinstance(params, dict) else {}
                migrated = params.get("migrate_to_chat_id")
                if isinstance(migrated, int) and not isinstance(migrated, bool) and migrated < 0 and str(migrated) != lane.chat:
                    old = lane.chat
                    with self.lock:
                        lane.chat = str(migrated)
                        self.lanes[self.key(lane.token, lane.chat)] = lane
                    if self.on_migrate:
                        try:
                            self.on_migrate(lane.token, old, lane.chat)
                        except Exception:
                            logger.warning("Telegram: destino migrado no envio; falha ao salvar a configuração.")
                    continue
                delay = params.get("retry_after")
                if result.kind == "rate_limited" and isinstance(delay, int) and not isinstance(delay, bool) and 0 <= delay <= 30 and waited + delay <= 60 and attempt < 3:
                    waited += delay
                    self._wait(delay, cancelled)
                    continue
                if reading and response.status_code >= 500 and attempt == 0:
                    continue
                return result
            except requests.ConnectTimeout:
                result = Result(False, "network_error", "O servidor não consegue conectar ao Telegram. Confira a internet, o DNS e o acesso a api.telegram.org no servidor.")
                if attempt < (1 if reading else 2):
                    self._wait(1, cancelled)
                    continue
                return result
            except requests.RequestException:
                # A timed-out write may already have arrived; never send it twice blindly.
                result = Result(False, "network_error", "Não foi possível confirmar o envio. Confira a internet e o DNS do servidor e use Enviar mensagem de teste.")
                if reading and attempt == 0:
                    continue
                return result
            finally:
                if not reading:
                    lane.next_send = self.clock() + (3.1 if lane.chat.startswith(("-", "@")) else 1.05)
        return result

    def _message(self, lane, markup):
        result = Result(False, "empty_message", "A mensagem está vazia.")
        for text, entities in formatted_parts(markup, 4096):
            result = self._request(lane, "sendMessage", {"text": text, "entities": entities, "link_preview_options": {"is_disabled": True}})
            if not result.ok:
                break
        self._record(lane, result, "sendMessage")
        return result

    def enqueue_message(self, token, chat, markup):
        return self._submit(token, chat, lambda lane: self._message(lane, markup))

    def send_message(self, token, chat, markup):
        return self.enqueue_message(token, chat, markup).result()

    def send_video(self, token, chat, path, caption, cancelled=None):
        def send(lane):
            part, entities = next(formatted_parts(caption, 1024), ("", []))
            result = self._request(lane, "sendVideo", {"caption": part, "caption_entities": entities, "supports_streaming": True}, path, cancelled)
            self._record(lane, result, "sendVideo")
            return result
        return self._submit(token, chat, send).result()

    def verify(self, token, chat):
        if not token or not chat:
            return Result(False, "unconfigured", "Salve o token do bot e o Chat ID antes de verificar.")
        lane = self._lane(token, chat)
        bot = self._request(lane, "getMe", reading=True)
        result = bot
        if bot.ok:
            target = self._request(lane, "getChat", reading=True)
            result = target
            if target.ok and target.data.get("type") in {"group", "supergroup", "channel"}:
                member = self._request(lane, "getChatMember", {"user_id": bot.data["id"]}, reading=True)
                result = member
                permissions = target.data.get("permissions") or {}
                if member.ok:
                    role = member.data.get("status")
                    blocked = role in {"left", "kicked"}
                    if role == "restricted":
                        blocked |= not member.data.get("is_member", False) or not member.data.get("can_send_messages", False) or not member.data.get("can_send_videos", False)
                    if target.data.get("type") == "channel":
                        blocked |= role not in {"administrator", "creator"} or (role == "administrator" and not member.data.get("can_post_messages", False))
                    elif role == "member":
                        blocked |= permissions.get("can_send_messages") is False or permissions.get("can_send_videos") is False
                    if blocked:
                        result = Result(False, "permission_denied", "Permita que o bot envie mensagens e vídeos neste grupo/canal, ou adicione-o novamente.")
            if result.ok:
                result = Result(True, "verified", "Bot e destino verificados. Use Enviar mensagem de teste para confirmar a entrega.")
        self._record(lane, result, "verify")
        return result
