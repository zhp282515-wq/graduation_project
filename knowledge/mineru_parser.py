"""解析单个本地文件，落盘到 parser_data/<文件名>/ 下（full.md、content_list.json）。"""

import io
import re
import json
import os
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from utils.logger_tool import logger
from utils.path_tool import get_abs_path
from dataclasses import dataclass

load_dotenv(override=True)

_DEFAULT_BASE_URL = "https://mineru.net/api/v4"
_DEFAULT_PARSER_DATA_DIR = "knowledge/parser_data"
_STATE_DONE = "done"
_STATE_FAILED = "failed"

# MinerU 给产物加了 UUID 前缀（<uuid>_content_list.json），剥掉让下游读取稳定。
_UUID_PREFIX = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}_"
)


class MineruError(RuntimeError):
    """MinerU 解析失败。"""

@dataclass
class ParsedDocument:
    """一次解析的完整产物。doc_dir 下是 MinerU 原样解开的全部文件。"""
    source: Path
    doc_dir: Path
    markdown: str
    content_list: list[dict]

class MineruParser:
    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        *,
        model_version: str = "vlm",
        timeout: float = 60.0,
        poll_interval: float = 5.0,
        max_wait: float = 900.0,
        is_ocr: bool = False,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
        parser_data_dir: str | Path | None = None,
    ):
        key = token or os.getenv("MINERU_API_KEY")
        if not key:
            raise ValueError("缺少 MINERU_API_KEY：请在 .env 中配置")
        self.token = key
        self.base_url = (
            base_url or os.getenv("MINERU_BASE_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self.model_version = model_version
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_wait = max_wait
        self.is_ocr = is_ocr
        self.enable_formula = enable_formula
        self.enable_table = enable_table
        self.language = language
        self.parser_data_dir = Path(
            parser_data_dir or get_abs_path(_DEFAULT_PARSER_DATA_DIR)
        )

        # MinerU 及其结果 CDN 均为国内服务，必须绕过系统代理直连；
        # 否则本机代理会拦掉 CDN 的 TLS 握手（SSL: UNEXPECTED_EOF）。
        # trust_env=False 让 httpx 同时忽略环境变量和系统代理设置。
        self._http = httpx.Client(trust_env=False, timeout=self.timeout)

    def close(self) -> None:
        self._http.close()

    def parse_file(self, file_path: str | Path) -> ParsedDocument:
        """解析单个本地文件，把 MinerU 返回的整个 zip 解到 parser_data/<文件名>/ 下。"""
        path = Path(file_path)
        if not path.is_file():
            raise MineruError(f"文件不存在：{path}")

        batch_id, upload_url = self._request_upload_url(path)
        self._upload(upload_url, path)
        zip_url = self._poll_batch(batch_id)
        zip_bytes = self._download_zip(zip_url)

        doc_dir = self.parser_data_dir / path.stem
        names = self._extract_all(zip_bytes, doc_dir)
        self._normalize_names(doc_dir)
        markdown, content_list = self._read_artifacts(doc_dir)

        logger.info(
            "MinerU 解析完成：%s -> %s（%d 个文件, %d 个内容块）",
            path.name, doc_dir, len(names), len(content_list),
        )
        return ParsedDocument(
            source=path,
            doc_dir=doc_dir,
            markdown=markdown,
            content_list=content_list,
        )

    # ---- 内部步骤 ----

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }



    def _download_zip(self, zip_url: str) -> bytes:
        resp = self._http.get(zip_url)
        if resp.status_code != 200:
            raise MineruError(f"下载解析结果失败 HTTP {resp.status_code}")
        return resp.content

    def _extract_all(self, zip_bytes: bytes, doc_dir: Path) -> list[str]:
        """把整个 zip 解到 doc_dir，返回解出的文件相对路径列表。"""
        doc_dir.mkdir(parents=True, exist_ok=True)
        root = doc_dir.resolve()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            for name in names:
                target = (doc_dir / name).resolve()
                # 防目录穿越：条目路径必须落在 doc_dir 内
                if not target.is_relative_to(root):
                    logger.warning("跳过可疑的压缩包路径：%s", name)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
        return names

    def _read_artifacts(self, doc_dir: Path) -> tuple[str, list[dict]]:
        """从解析产物里读出 markdown 与 content_list.json（已规范化名字）。"""
        md_path = doc_dir / "full.md"
        if not md_path.is_file():
            mds = list(doc_dir.glob("*.md"))
            if not mds:
                raise MineruError(f"{doc_dir} 下没有 markdown")
            md_path = mds[0]
        markdown = md_path.read_text(encoding="utf-8", errors="replace")

        cl_path = doc_dir / "content_list.json"
        if not cl_path.is_file():
            raise MineruError(f"{doc_dir} 下没有 content_list.json（目录：{[p.name for p in doc_dir.iterdir()]}）")
        try:
            content_list = json.loads(cl_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MineruError(f"content_list.json 解析失败：{exc}") from exc
        if not isinstance(content_list, list):
            raise MineruError("content_list.json 顶层不是列表")
        return markdown, content_list



    def _request_upload_url(self, path: Path) -> tuple[str, str]:
        payload = {
            # data_id 仅支持 ASCII 标识且最长 128 字符，不能直接使用本地文件名。
            "files": [{"name": path.name, "data_id": uuid4().hex}],
            "model_version": self.model_version,
            "is_ocr": self.is_ocr,
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
        }
        resp = self._http.post(
            f"{self.base_url}/file-urls/batch",
            headers=self._headers(),
            json=payload,
        )
        data = self._unwrap(resp, "申请上传链接")
        logger.info("MinerU 上传链接已获取：batch=%s, file=%s", data["batch_id"], path.name)
        return data["batch_id"], data["file_urls"][0]

    def _upload(self, upload_url: str, path: Path) -> None:
        # 签名上传必须不带 Content-Type，否则 OSS 校验签名失败。
        content = path.read_bytes()
        up = self._http.put(upload_url, content=content)
        if up.status_code not in (200, 201):
            raise MineruError(f"上传失败 HTTP {up.status_code}: {up.text[:200]}")

    def _poll_batch(self, batch_id: str) -> str:
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        started = time.perf_counter()
        last_state = ""

        while True:
            resp = self._http.get(url, headers=self._headers())
            data = self._unwrap(resp, "查询解析结果")
            results = data.get("extract_result") or []
            if not results:
                raise MineruError("MinerU 返回的 extract_result 为空")

            item = results[0]
            state = item.get("state", "")
            if state != last_state:
                logger.info("MinerU 任务状态：%s", state)
                last_state = state

            if state == _STATE_DONE:
                zip_url = item.get("full_zip_url")
                if not zip_url:
                    raise MineruError("任务已完成但缺少 full_zip_url")
                return zip_url
            if state == _STATE_FAILED:
                raise MineruError(f"MinerU 解析失败：{item.get('err_msg') or '未知错误'}")
            if time.perf_counter() - started > self.max_wait:
                raise MineruError(f"MinerU 解析超时（>{self.max_wait:.0f}s），最后状态 {state}")

            time.sleep(self.poll_interval)

    def _normalize_names(self, doc_dir: Path) -> None:
        """剥掉文件名上的 UUID 前缀，如 <uuid>_content_list.json -> content_list.json。"""
        for entry in doc_dir.iterdir():
            if not entry.is_file():
                continue
            new_name = _UUID_PREFIX.sub("", entry.name)
            if new_name == entry.name:
                continue
            target = doc_dir / new_name
            if target.exists():
                target.unlink()
            entry.rename(target)
            logger.debug("规范化文件名：%s -> %s", entry.name, new_name)

    @staticmethod
    def _unwrap(resp: httpx.Response, action: str) -> dict:
        """统一处理两种响应信封：业务 {code,data,msg} 与网关 {success,msgCode,msg}。"""
        if resp.status_code != 200:
            raise MineruError(f"{action}失败 HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
        except Exception as exc:
            raise MineruError(f"{action}响应不是合法 JSON：{exc}") from exc

        if body.get("success") is False:
            raise MineruError(f"{action}失败 [{body.get('msgCode')}]：{body.get('msg')}")
        if body.get("code") != 0:
            raise MineruError(f"{action}失败 [{body.get('code')}]：{body.get('msg')}")

        data = body.get("data")
        if not isinstance(data, dict):
            raise MineruError(f"{action}响应缺少 data 字段")
        return data


if __name__ == "__main__":
    parser = MineruParser()
    try:
        doc = parser.parse_file(get_abs_path("data/02-客户信息表清洗.xlsx"))
        print("产物目录:", doc.doc_dir)
        print("markdown 长度:", len(doc.markdown))
        print("内容块数:", len(doc.content_list))
        print("\n=== content_list 前 3 项 ===")
        for item in doc.content_list[:3]:
            print({
                "type": item.get("type"),
                "text_level": item.get("text_level"),
                "page_idx": item.get("page_idx"),
                "text": (item.get("text") or "")[:60],
            })
    finally:
        parser.close()
