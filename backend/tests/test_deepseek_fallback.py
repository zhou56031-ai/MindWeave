"""凭据回退只在允许的失败和流输出开始前发生。"""

import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.services import deepseek_client as module


class BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
        raise httpx.ReadError("connection closed")


class DeepSeekFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.original_client = httpx.AsyncClient
        self.keys = patch.object(module, "_api_keys", return_value=["primary", "backup"])
        self.keys.start()

    def tearDown(self):
        self.keys.stop()

    def client_with(self, handler):
        transport = httpx.MockTransport(handler)
        return patch.object(
            module.httpx, "AsyncClient",
            side_effect=lambda **kwargs: self.original_client(transport=transport, **kwargs),
        )

    async def test_primary_success_does_not_use_backup(self):
        def handler(request):
            self.calls.append(request.headers["Authorization"])
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ok"}}],
            })

        with self.client_with(handler):
            result = await module.deepseek_client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(result, "ok")
        self.assertEqual(self.calls, ["Bearer primary"])

    async def test_auth_failure_uses_backup(self):
        def handler(request):
            key = request.headers["Authorization"]
            self.calls.append(key)
            if key == "Bearer primary":
                return httpx.Response(401)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "backup ok"}}],
            })

        with self.client_with(handler):
            result = await module.deepseek_client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(result, "backup ok")
        self.assertEqual(self.calls, ["Bearer primary", "Bearer backup"])

    async def test_bad_request_does_not_use_backup(self):
        def handler(request):
            self.calls.append(request.headers["Authorization"])
            return httpx.Response(422)

        with self.client_with(handler):
            with self.assertRaises(HTTPException):
                await module.deepseek_client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(self.calls, ["Bearer primary"])

    async def test_stream_auth_failure_uses_backup(self):
        def handler(request):
            key = request.headers["Authorization"]
            self.calls.append(key)
            if key == "Bearer primary":
                return httpx.Response(401)
            data = json.dumps({"choices": [{"delta": {"content": "backup"}}]})
            return httpx.Response(200, text=f"data: {data}\n\ndata: [DONE]\n\n")

        with self.client_with(handler):
            parts = [part async for part in module.deepseek_client.stream_chat(
                [{"role": "user", "content": "test"}]
            )]
        self.assertEqual(parts, ["backup"])
        self.assertEqual(self.calls, ["Bearer primary", "Bearer backup"])

    async def test_stream_does_not_switch_after_partial_answer(self):
        def handler(request):
            self.calls.append(request.headers["Authorization"])
            return httpx.Response(200, stream=BrokenStream())

        parts = []
        with self.client_with(handler):
            with self.assertRaises(HTTPException):
                async for part in module.deepseek_client.stream_chat(
                    [{"role": "user", "content": "test"}]
                ):
                    parts.append(part)
        self.assertEqual(parts, ["first"])
        self.assertEqual(self.calls, ["Bearer primary"])


if __name__ == "__main__":
    unittest.main()
