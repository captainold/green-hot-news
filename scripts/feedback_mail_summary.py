#!/usr/bin/env python3
"""feedback@ywm.life 邮件汇总（2026-08-27 反馈渠道方案）。

Cloudflare Email Routing 把 feedback@ywm.life 转发到老温 Gmail，
本脚本用 Python 标准库（imaplib + email）收信，供 cron 每周汇总进待办。

用法：
    python3.11 scripts/feedback_mail_summary.py [--days 7] [--mark-seen]

凭据：.env 的 feedback_imap_user（Gmail 地址）+ feedback_imap_pass（App Password 16 位）
输出：stdout 结构化文本（发件人 / 主题 / 日期 / 正文摘要），cron agent 据此提炼。
"""
from __future__ import annotations

import argparse
import email
import email.header
import imaplib
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
BODY_PREVIEW_CHARS = 300


def _env_value(key: str) -> str:
    """从项目 .env 读值（键名小写，兼容带引号）。"""
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def _decode_header(raw: str) -> str:
    """解码 RFC2047 编码的邮件头（=?UTF-8?B?...?=）。"""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for data, charset in parts:
        if isinstance(data, bytes):
            try:
                out.append(data.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(data.decode("utf-8", errors="replace"))
        else:
            out.append(data)
    return "".join(out).strip()


def _first_text_body(msg: email.message.Message) -> str:
    """取纯文本正文（优先 text/plain，回退 html 去标签）。"""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    return re.sub(r"\s+", " ", text).strip()
                except Exception:
                    continue
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="feedback 邮箱汇总")
    ap.add_argument("--days", type=int, default=7, help="汇总最近 N 天（默认 7）")
    ap.add_argument("--mark-seen", action="store_true", help="读后标记已读（默认不标记，靠日期窗口判增量）")
    args = ap.parse_args()

    user = _env_value("feedback_imap_user")
    pwd = _env_value("feedback_imap_pass")
    if not user or not pwd:
        print("❌ .env 缺 feedback_imap_user / feedback_imap_pass（Gmail App Password）", file=sys.stderr)
        return 2

    since = (datetime.now() - timedelta(days=args.days)).strftime("%d-%b-%Y")
    try:
        m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
        m.login(user, pwd)
        m.select("INBOX")
        typ, data = m.search(None, f'(SINCE "{since}")')
        if typ != "OK":
            print("搜索失败", file=sys.stderr)
            return 1
        ids = data[0].split()
        print(f"📬 feedback 邮箱最近 {args.days} 天：{len(ids)} 封\n")
        for i in ids:
            typ, msg_data = m.fetch(i, "(RFC822)")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            frm = _decode_header(msg.get("From", ""))
            subj = _decode_header(msg.get("Subject", ""))
            date_raw = msg.get("Date", "")
            try:
                date_s = parsedate_to_datetime(date_raw).astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_s = date_raw
            body = _first_text_body(msg)
            preview = re.sub(r"\s+", " ", body).strip()[:BODY_PREVIEW_CHARS]
            print(f"── 邮件 {i.decode()} ──────────────")
            print(f"发件人: {frm}")
            print(f"主题:   {subj}")
            print(f"日期:   {date_s}")
            if preview:
                print(f"摘要:   {preview}")
            print()
            if args.mark_seen:
                m.store(i, "+FLAGS", "\\Seen")
        m.logout()
    except Exception as e:
        print(f"❌ IMAP 错误: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
