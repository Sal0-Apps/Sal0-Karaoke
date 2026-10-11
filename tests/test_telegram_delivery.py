"""Exercise real delivery code with controlled Telegram failures and concurrent stages."""
import ast
from concurrent.futures import ThreadPoolExecutor
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
import requests

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "app"))
from telegram_delivery import TelegramDelivery, formatted_parts, units


def reply(data, code=200):
    return SimpleNamespace(status_code=code, json=lambda: data)


def success(method, payload=None):
    data = {"id": 123, "is_bot": True} if method == "getMe" else {"id": -100123, "type": "supergroup"} if method == "getChat" else {"status": "administrator"} if method == "getChatMember" else {"message_id": 42}
    return reply({"ok": True, "result": data if payload is None else payload})


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []
    def read(self):
        return self.now
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class TelegramDeliveryTests(unittest.TestCase):
    def client(self, handler):
        clock = Clock()
        return TelegramDelivery(post=handler, clock=clock.read, sleep=clock.sleep), clock

    def test_http_200_is_not_success_without_a_confirmed_message(self):
        for data in (None, [], {"ok": False, "error_code": 403}, {"ok": True}, {"ok": True, "result": {}}):
            with self.subTest(data=data):
                client, _ = self.client(lambda *args, **kwargs: reply(data))
                result = client.send_message("private-token", "chat", "Hello")
                self.assertFalse(result.ok)
                self.assertFalse(client.status("private-token", "chat")["last_delivery"]["ok"])

    def test_rate_limit_waits_then_retries_the_same_message_once(self):
        calls = []
        def post(url, **kwargs):
            calls.append(kwargs["json"])
            return reply({"ok": False, "error_code": 429, "parameters": {"retry_after": 2}}, 429) if len(calls) == 1 else success("sendMessage")
        client, clock = self.client(post)
        self.assertTrue(client.send_message("bot", "-1001", "Hello").ok)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertGreaterEqual(clock.now, 2)
        self.assertTrue(client.status("bot", "-1001")["last_delivery"]["ok"])

    def test_persistent_rate_limit_is_bounded_and_visible(self):
        calls = []
        def post(url, **kwargs):
            calls.append(url)
            return reply({"ok": False, "error_code": 429, "parameters": {"retry_after": 2}}, 429)
        client, _ = self.client(post)
        result = client.send_message("bot", "-1001", "Hello")
        self.assertEqual(result.kind, "rate_limited")
        self.assertEqual(len(calls), 4)

    def test_group_migration_retries_new_destination_and_updates_future_messages(self):
        chats, saved = [], []
        def post(url, **kwargs):
            chats.append(kwargs["json"]["chat_id"])
            return reply({"ok": False, "error_code": 400, "parameters": {"migrate_to_chat_id": -100123}}, 400) if len(chats) == 1 else success("sendMessage")
        client, _ = self.client(post)
        client.on_migrate = lambda *args: saved.append(args)
        self.assertTrue(client.send_message("bot", "-123", "First").ok)
        self.assertTrue(client.send_message("bot", "-123", "Second").ok)
        self.assertTrue(client.send_message("bot", "-100123", "Third").ok)
        self.assertEqual(chats, ["-123", "-100123", "-100123", "-100123"])
        self.assertEqual(saved, [("bot", "-123", "-100123")])

    def test_video_retry_reopens_the_complete_attachment(self):
        uploads = []
        def post(url, **kwargs):
            uploads.append(kwargs["files"]["video"][1].read())
            return reply({"ok": False, "error_code": 429, "parameters": {"retry_after": 0}}, 429) if len(uploads) == 1 else success("sendVideo")
        client, _ = self.client(post)
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "full.mp4"
            video.write_bytes(b"complete video")
            self.assertTrue(client.send_video("bot", "chat", str(video), "<b>Done</b>").ok)
        self.assertEqual(uploads, [b"complete video", b"complete video"])

    def test_ambiguous_timeouts_and_connection_losses_do_not_duplicate_writes(self):
        for failure in (requests.ReadTimeout("secret URL"), requests.ConnectionError("private-token")):
            calls = []
            def post(url, **kwargs):
                calls.append(url)
                raise failure
            client, _ = self.client(post)
            with self.assertLogs("telegram", level="WARNING") as logs:
                result = client.send_message("private-token", "chat", "Hello")
            self.assertEqual(result.kind, "network_error")
            self.assertEqual(len(calls), 1)
            self.assertNotIn("private-token", str(logs.output) + str(result.public()))
            self.assertNotIn("secret URL", str(logs.output) + str(result.public()))

    def test_connect_timeout_can_retry_before_any_delivery(self):
        calls = []
        def post(url, **kwargs):
            calls.append(url)
            if len(calls) == 1: raise requests.ConnectTimeout("private-token")
            return success("sendMessage")
        client, _ = self.client(post)
        self.assertTrue(client.send_message("bot", "chat", "Hello").ok)
        self.assertEqual(len(calls), 2)

    def test_notifications_are_fifo_and_video_waits_without_blocking_other_chats(self):
        started, release = threading.Event(), threading.Event()
        order = []
        def post(url, **kwargs):
            method = url.rsplit("/", 1)[1]
            body = kwargs.get("json", kwargs.get("data"))
            if body["chat_id"] == "owner":
                if body.get("text") == "First":
                    started.set()
                    if not release.wait(3): raise RuntimeError("test timeout")
                order.append(body.get("text", "video"))
            return success(method)
        client = TelegramDelivery(post=post, sleep=lambda _: None)
        first = client.enqueue_message("bot", "owner", "First")
        self.assertTrue(started.wait(2))
        second = client.enqueue_message("bot", "owner", "Second")
        self.assertFalse(first.done())
        self.assertFalse(second.done())
        self.assertTrue(client.send_message("bot", "other", "Independent").ok)
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor() as pool:
            path = Path(folder) / "video.mp4"; path.write_bytes(b"video")
            final = pool.submit(client.send_video, "bot", "owner", str(path), "Done")
            release.set()
            self.assertTrue(final.result(timeout=3).ok)
        self.assertEqual(order, ["First", "Second", "video"])
        self.assertEqual(client.status("bot", "owner")["pending"], 0)

    def test_group_requests_are_spaced_apart(self):
        client, clock = self.client(lambda url, **kwargs: success("sendMessage"))
        for _ in range(3): self.assertTrue(client.send_message("bot", "-1001", "Step").ok)
        self.assertAlmostEqual(clock.now, 6.2)

    def test_verify_never_sends_a_message_and_checks_group_permissions(self):
        for member, expected in (({"status": "administrator"}, True), ({"status": "left"}, False),
            ({"status": "restricted", "is_member": True, "can_send_messages": True, "can_send_videos": False}, False)):
            methods = []
            def post(url, **kwargs):
                method = url.rsplit("/", 1)[1]; methods.append(method)
                return success(method, member if method == "getChatMember" else None)
            client, _ = self.client(post)
            self.assertEqual(client.verify("bot", "-1001").ok, expected)
            self.assertEqual(methods, ["getMe", "getChat", "getChatMember"])

    def test_verify_read_can_retry_invalid_proxy_replies(self):
        methods = []
        def post(url, **kwargs):
            method = url.rsplit("/", 1)[1]; methods.append(method)
            return reply(None, 503) if len(methods) == 1 else success(method)
        client, _ = self.client(post)
        self.assertTrue(client.verify("bot", "-1001").ok)
        self.assertEqual(methods, ["getMe", "getMe", "getChat", "getChatMember"])

    def test_malformed_success_payloads_never_claim_a_verified_connection(self):
        for method, data in (("getMe", {"id": True, "is_bot": True}),
                ("getMe", {"id": 123, "is_bot": False}),
                ("getChat", {"id": -123, "type": "group", "permissions": []}),
                ("getChatMember", {"status": "unknown"})):
            def post(url, **kwargs):
                current = url.rsplit("/", 1)[1]
                return success(current, data if current == method else None)
            client, _ = self.client(post)
            self.assertFalse(client.verify("bot", "-1001").ok)

    def test_video_failure_remains_visible_after_a_successful_link_message(self):
        def post(url, **kwargs):
            return reply({"ok": False, "error_code": 403}, 403) if url.endswith("/sendVideo") else success("sendMessage")
        client, _ = self.client(post)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "video.mp4"; path.write_bytes(b"video")
            self.assertFalse(client.send_video("bot", "chat", str(path), "Done").ok)
        self.assertTrue(client.send_message("bot", "chat", "Use these links").ok)
        status = client.status("bot", "chat")
        self.assertTrue(status["last_delivery"]["ok"])
        self.assertFalse(status["last_video_delivery"]["ok"])

    def test_multiple_bots_with_the_same_chat_have_separate_status(self):
        client, _ = self.client(lambda url, **kwargs: reply({"ok": False, "error_code": 401}, 401) if "bad-bot" in url else success("sendMessage"))
        self.assertFalse(client.send_message("bad-bot", "chat", "Bad").ok)
        self.assertTrue(client.send_message("good-bot", "chat", "Good").ok)
        self.assertEqual(client.status("bad-bot", "chat")["state"], "invalid_token")
        self.assertEqual(client.status("good-bot", "chat")["state"], "verified")

    def test_invalid_token_chat_and_permission_errors_are_actionable(self):
        for code, description, kind in ((401, "private body", "invalid_token"),
            (400, "Bad Request: chat not found private-token", "chat_not_found"),
            (403, "Forbidden: bot was blocked private-token", "permission_denied")):
            calls = []
            def post(url, **kwargs):
                calls.append(url)
                return reply({"ok": False, "error_code": code, "description": description}, code)
            client, _ = self.client(post)
            result = client.send_message("private-token", "chat", "Hello")
            self.assertEqual(result.kind, kind)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("private-token", str(result.public()))

    def test_cancellation_while_waiting_to_retry_propagates(self):
        def post(url, **kwargs):
            return reply({"ok": False, "error_code": 429, "parameters": {"retry_after": 2}}, 429)
        client, _ = self.client(post)
        count = []
        def cancel():
            count.append(1)
            if len(count) > 1: raise InterruptedError("cancelled")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "video.mp4"; path.write_bytes(b"video")
            with self.assertRaises(InterruptedError): client.send_video("bot", "chat", str(path), "Done", cancelled=cancel)

    def test_unicode_text_splitting_and_link_entities_preserve_every_character(self):
        title = "🎤 Café & <voz> " * 600
        markup = f'<b>{html.escape(title)}</b>\n<a href="https://example.org/file?a=1&amp;b=2">Download</a>'
        parts = list(formatted_parts(markup, 4096))
        self.assertEqual("".join(text for text, _ in parts), title + "\nDownload")
        self.assertTrue(all(units(text) <= 4096 for text, _ in parts))
        links = [entity for _, entities in parts for entity in entities if entity["type"] == "text_link"]
        self.assertEqual(links[0]["url"], "https://example.org/file?a=1&b=2")
        for text, entities in parts:
            for entity in entities:
                self.assertLessEqual(entity["offset"] + entity["length"], units(text))

    def test_caption_is_bounded_and_uses_entities_without_html_parsing(self):
        sent = []
        def post(url, **kwargs):
            sent.append(kwargs["data"])
            return success("sendVideo")
        client, _ = self.client(post)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "video.mp4"; path.write_bytes(b"video")
            self.assertTrue(client.send_video("bot", "chat", str(path), "<b>" + "🎵" * 900 + "</b>").ok)
        self.assertLessEqual(units(sent[0]["caption"]), 1024)
        self.assertNotIn("parse_mode", sent[0])
        self.assertEqual(json.loads(sent[0]["caption_entities"])[0]["length"], units(sent[0]["caption"]))


def settings_app(folder, sender, users):
    app = FastAPI()
    owner = {"username": "alice", "role": "user"}
    names = {"telegram_notice", "telegram_escape", "masked_telegram_token", "telegram_file_for_user",
        "load_telegram_config", "write_telegram_config", "persist_telegram_chat_migration", "get_notification_targets",
        "get_telegram_config", "get_telegram_delivery_status", "save_telegram_config", "verify_telegram_connection", "test_telegram_delivery"}
    tree = ast.parse((ROOT / "app/main.py").read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and (node.name in names or node.name == "TelegramModel")]
    scope = dict(app=app, Depends=Depends, HTTPException=HTTPException, BaseModel=BaseModel,
        get_current_user=lambda: owner, is_admin=lambda user: user["role"] == "admin",
        config_path=lambda user, name: str(Path(folder) / user["username"] / name),
        TELEGRAM_FILE=str(Path(folder) / "admin" / "telegram.json"), TELEGRAM_DELIVERY=sender,
        telegram_config_lock=threading.RLock(), os=os, json=json, tempfile=tempfile, re=re, html=html,
        logger=logging.getLogger("test-telegram"), load_users=lambda: users)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "telegram-settings", "exec"), scope)
    sender.on_migrate = scope["persist_telegram_chat_migration"]
    return TestClient(app), scope, owner


class TelegramSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.posts = []
        def post(url, **kwargs):
            self.posts.append((url.rsplit("/", 1)[1], kwargs))
            return success(url.rsplit("/", 1)[1])
        self.sender = TelegramDelivery(post=post, sleep=lambda _: None)
        self.users = {"alice": {"role": "user"}, "bob": {"role": "user"}, "root": {"role": "admin"}}
        self.client, self.scope, self.owner = settings_app(self.folder.name, self.sender, self.users)
        self.token = "123456789:private_secret_token"

    def save(self, chat="-100123", token=None):
        return self.client.post("/api/telegram", json={"telegram_token": token or self.token, "telegram_chat_id": chat})

    def test_saved_configuration_is_masked_and_not_claimed_to_be_active(self):
        self.assertEqual(self.save().status_code, 200)
        data = self.client.get("/api/telegram").json()
        self.assertTrue(data["configured"])
        self.assertEqual(data["delivery"]["state"], "unverified")
        self.assertNotIn(self.token, json.dumps(data))
        self.assertEqual(self.posts, [])
        self.assertEqual(os.stat(Path(self.folder.name) / "alice/telegram.json").st_mode & 0o777, 0o600)

    def test_verify_is_read_only_and_test_sends_once_only_to_own_bot(self):
        self.save()
        self.assertTrue(self.client.post("/api/telegram/verify").json()["ok"])
        self.assertEqual([method for method, _ in self.posts], ["getMe", "getChat", "getChatMember"])
        self.posts.clear()
        self.assertTrue(self.client.post("/api/telegram/test").json()["ok"])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0][0], "sendMessage")
        self.assertEqual(self.posts[0][1]["json"]["chat_id"], "-100123")

    def test_masked_token_keeps_original_and_invalid_inputs_do_not_overwrite_it(self):
        self.save()
        masked = self.client.get("/api/telegram").json()["telegram_token"]
        self.assertEqual(self.save("-100222", masked).status_code, 200)
        for chat, token in (("not a chat", self.token), ("123", "bogus***mask"), ("123", "invalid token")):
            self.assertEqual(self.save(chat, token).status_code, 400)
        self.assertEqual(self.scope["load_telegram_config"](self.owner), {"telegram_token": self.token, "telegram_chat_id": "-100222"})

    def test_migration_is_saved_only_for_matching_credentials_and_chat(self):
        self.save("-123")
        bob = {"username": "bob", "role": "user"}
        self.scope["write_telegram_config"](self.scope["telegram_file_for_user"](bob), {"telegram_token": "other:bot", "telegram_chat_id": "-123"})
        self.scope["persist_telegram_chat_migration"](self.token, "-123", "-100123")
        self.assertEqual(self.scope["load_telegram_config"](self.owner)["telegram_chat_id"], "-100123")
        self.assertEqual(self.scope["load_telegram_config"](bob)["telegram_chat_id"], "-123")

    def test_legacy_numeric_id_and_broken_configuration_never_break_processing(self):
        path = Path(self.folder.name) / "alice/telegram.json"; path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"telegram_token": self.token, "telegram_chat_id": -100123}))
        self.assertEqual(self.client.get("/api/telegram").json()["telegram_chat_id"], "-100123")
        for invalid in ("null", "[]", "{incomplete"):
            path.write_text(invalid)
            response = self.client.get("/api/telegram")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["delivery"]["state"], "config_error")
            self.assertEqual(self.scope["get_notification_targets"](self.owner), [])

    def test_user_and_admin_results_remain_isolated(self):
        self.save()
        admin = {"username": "root", "role": "admin"}
        self.scope["write_telegram_config"](self.scope["telegram_file_for_user"](admin), {"telegram_token": "999:admin", "telegram_chat_id": "-100999"})
        targets = self.scope["get_notification_targets"](self.owner)
        self.assertEqual({target["telegram_chat_id"] for target in targets}, {"-100123", "-100999"})
        self.owner.update(username="bob", role="user")
        self.assertFalse(self.client.get("/api/telegram").json()["configured"])
        self.assertEqual(self.client.get("/api/telegram/status").json()["state"], "unconfigured")


if __name__ == "__main__":
    unittest.main()
