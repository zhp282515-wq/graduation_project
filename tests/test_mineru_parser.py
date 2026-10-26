import json
import unittest
from pathlib import Path

import httpx

from knowledge.mineru_parser import MineruParser


class MineruUploadRequestTests(unittest.TestCase):
    def setUp(self):
        self.requests = []

        def handle(request):
            self.requests.append(request)
            return httpx.Response(200, json={
                "code": 0,
                "data": {
                    "batch_id": "test-batch",
                    "file_urls": ["https://uploads.example.test/document"],
                },
            })

        self.parser = MineruParser(token="test-token")
        self.parser._http.close()
        self.parser._http = httpx.Client(transport=httpx.MockTransport(handle))
        self.addCleanup(self.parser.close)

    def test_filename_does_not_violate_data_id_contract(self):
        # 覆盖中文、空格和超过 128 字符的服务端落盘名；全程不读文件、不联网。
        names = [
            "example.pdf",
            "江西师范大学图书馆综合指南与最新情况_截至2026-10-25.pdf",
            "a" * 128 + ".pdf",
            "a" * 129 + ".pdf",
            "a" * 32 + "-" + "b" * 32 + "-" + "c" * 80 + ".pdf",
            "my report (final).pdf",
        ]
        for name in names:
            with self.subTest(name=name):
                result = self.parser._request_upload_url(Path(name))
                self.assertEqual(result, (
                    "test-batch", "https://uploads.example.test/document",
                ))
                request = self.requests[-1]
                self.assertEqual(request.method, "POST")
                self.assertEqual(request.url.path, "/api/v4/file-urls/batch")
                payload = json.loads(request.content)
                file = payload["files"][0]
                self.assertEqual(file["name"], name)
                self.assertLessEqual(len(file["data_id"]), 128)
                self.assertRegex(file["data_id"], r"^[A-Za-z0-9_.-]+$")

    def test_repeated_uploads_use_distinct_data_ids(self):
        for _ in range(2):
            self.parser._request_upload_url(Path("same.pdf"))
        ids = [json.loads(request.content)["files"][0]["data_id"]
               for request in self.requests]
        self.assertNotEqual(ids[0], ids[1])


if __name__ == "__main__":
    unittest.main()
