#!/usr/bin/env python
"""Watch openUBMC internship task issues and notify on new claimable work."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any


GITCODE_SOURCES: list[dict[str, Any]] = [
    {
        "key": "openubmc",
        "name": "OpenUBMC",
        "project_id": 4064052,
        "web_url": "https://gitcode.com/openUBMC/community",
        "referer": "https://gitcode.com/openUBMC/community/issues",
        "title_keywords": ["\u5f00\u6e90\u5b9e\u4e60"],
        "label_keywords": ["intern"],
        "include_all_open": False,
        "include_details": True,
        "detail_title_keywords": ["SIG\u4efb\u52a1"],
    },
    {
        "key": "openeuler",
        "name": "openEuler",
        "project_id": 7678559,
        "web_url": "https://gitcode.com/openeuler/opensource-intern",
        "referer": "https://gitcode.com/openeuler/opensource-intern/issues",
        "title_keywords": [],
        "label_keywords": [],
        "include_all_open": True,
        "include_details": False,
    },
    {
        "key": "mindspore",
        "name": "MindSpore",
        "project_id": 8660827,
        "web_url": "https://gitcode.com/mindspore/community",
        "referer": "https://gitcode.com/mindspore/community/issues",
        "title_keywords": ["\u5f00\u6e90\u5b9e\u4e60"],
        "label_keywords": [],
        "include_all_open": False,
        "include_details": True,
        "detail_title_keywords": ["SIG\u4efb\u52a1"],
    },
    {
        "key": "chaspark-ascendnpu-ir",
        "name": "Chaspark/AscendNPU IR",
        "project_id": 7494336,
        "web_url": "https://gitcode.com/Ascend/AscendNPU-IR",
        "referer": "https://gitcode.com/Ascend/AscendNPU-IR/issues/274",
        "title_keywords": [],
        "label_keywords": [],
        "include_all_open": False,
        "issue_iids": [274],
        "include_details": True,
    },
]

GITHUB_SOURCES: list[dict[str, Any]] = []

CLAIMABLE_STATUS_WORDS = (
    "\u5f85\u8ba4\u9886",
    "\u672a\u8ba4\u9886",
    "\u53ef\u8ba4\u9886",
    "open",
    "opened",
)

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://gitcode.com",
    "Referer": "https://gitcode.com/openUBMC/community/issues",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass(frozen=True)
class TaskItem:
    key: str
    title: str
    url: str
    source: str
    status: str
    assignee: str = ""
    sig: str = ""
    score: str = ""
    created_at: str = ""
    updated_at: str = ""
    labels: str = ""

    @property
    def digest(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def is_claimable(self) -> bool:
        status = (self.status or "").strip().lower()
        return any(word.lower() in status for word in CLAIMABLE_STATUS_WORDS)


def utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def resolve_relative_path(path: str) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    cwd_target = Path.cwd() / target
    if cwd_target.exists():
        return cwd_target
    return Path(__file__).resolve().parent / target


def load_env_file(path: str) -> None:
    env_path = resolve_relative_path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def fetch_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} while fetching {url}: {body[:300]}") from exc
    return json.loads(data)


def gitcode_issues_api(source: dict[str, Any]) -> str:
    return f"https://gitcode.com/issuepr/api/v1/issue/{source['project_id']}/issues"


def gitcode_headers(source: dict[str, Any]) -> dict[str, str]:
    return {
        "Origin": "https://gitcode.com",
        "Referer": str(source.get("referer") or source["web_url"]),
    }


def fetch_gitcode_issues(
    source: dict[str, Any],
    state: str = "opened",
    per_page: int = 100,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    if source.get("issue_iids"):
        return [
            fetch_json(f"{gitcode_issues_api(source)}/{iid}", headers=gitcode_headers(source))
            for iid in source["issue_iids"]
        ]

    issues: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = fetch_json(
            gitcode_issues_api(source),
            {
                "state": state,
                "page": page,
                "per_page": per_page,
            },
            headers=gitcode_headers(source),
        )
        batch = payload.get("issues") or []
        issues.extend(batch)
        if len(batch) < per_page:
            break
    return issues


def issue_url(source: dict[str, Any], iid: int | str) -> str:
    return f"{source['web_url']}/issues/{iid}"


def label_names(issue: dict[str, Any]) -> list[str]:
    labels = issue.get("labels") or []
    return [str(label.get("name") or label.get("title") or "") for label in labels]


def is_intern_issue(issue: dict[str, Any], source: dict[str, Any]) -> bool:
    if source.get("issue_iids"):
        return True
    if source.get("include_all_open"):
        return True
    title = str(issue.get("title") or "")
    labels = {name.lower() for name in label_names(issue)}
    label_keywords = {str(label).lower() for label in source.get("label_keywords", [])}
    title_keywords = [str(keyword) for keyword in source.get("title_keywords", [])]
    return bool(labels & label_keywords) or any(keyword in title for keyword in title_keywords)


def should_fetch_issue_detail(issue: dict[str, Any], source: dict[str, Any]) -> bool:
    if not source.get("include_details", True):
        return False
    keywords = [str(keyword) for keyword in source.get("detail_title_keywords", [])]
    if not keywords:
        return True
    title = str(issue.get("title") or "")
    return any(keyword in title for keyword in keywords)


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [part.strip() for part in line.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells if cell)


def extract_markdown_link(cell: str) -> tuple[str, str]:
    match = re.search(r"\[([^\]]+)\]\((https?://[^)]+)\)", cell)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    url_match = re.search(r"https?://\S+", cell)
    return cell.strip(), url_match.group(0).rstrip(")") if url_match else ""


def stable_key_for_table_row(source_key: str, source_iid: int, title: str, url: str) -> str:
    linked_iid = re.search(r"/issues/(\d+)", url)
    if linked_iid:
        return f"table:{source_key}:{source_iid}:issue:{linked_iid.group(1)}"
    short_hash = hashlib.sha1(f"{source_key}|{source_iid}|{title}|{url}".encode("utf-8")).hexdigest()[:12]
    return f"table:{source_key}:{source_iid}:{short_hash}"


def parse_task_table(description: str, source_issue: dict[str, Any], source: dict[str, Any]) -> list[TaskItem]:
    source_iid = int(source_issue["iid"])
    rows: list[TaskItem] = []
    current_header: list[str] = []

    def column(cells: list[str], names: list[str]) -> str:
        for name in names:
            for index, header in enumerate(current_header):
                if name in header and index < len(cells):
                    return cells[index]
        return ""

    for raw_line in description.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            current_header = []
            continue
        cells = split_markdown_row(line)
        if is_separator_row(cells):
            continue
        headerish = "".join(cells[:3])
        if ("\u9898\u76ee" in headerish and "\u5206\u503c" in headerish) or (
            "\u4efb\u52a1ID" in headerish and "\u4efb\u52a1\u63cf\u8ff0" in headerish
        ):
            current_header = cells
            continue

        if "\u4efb\u52a1ID" in "".join(current_header) and "\u4efb\u52a1\u63cf\u8ff0" in "".join(current_header):
            detail_cell = column(cells, ["\u4efb\u52a1ID"])
            title = column(cells, ["\u4efb\u52a1\u63cf\u8ff0"])
            score = column(cells, ["\u5206\u503c"])
            status = column(cells, ["\u72b6\u6001"])
            assignee = column(cells, ["\u627f\u63a5\u4eba", "\u4efb\u52a1\u8ba4\u9886\u4eba"])
            if not title:
                continue
            _link_text, url = extract_markdown_link(detail_cell)
            if not url:
                url = issue_url(source, source_iid)
            rows.append(
                TaskItem(
                    key=stable_key_for_table_row(str(source["key"]), source_iid, title, url),
                    title=title,
                    url=url,
                    source=f"{source['name']} task pool #{source_iid}",
                    status=status,
                    assignee=assignee,
                    sig=str(source["name"]),
                    score=score,
                    updated_at=str(source_issue.get("updated_at") or ""),
                )
            )
            continue

        if len(cells) < 7:
            continue
        sig, title, score, _eta, detail_cell, status, assignee = cells[:7]
        if not title or title == "---":
            continue
        _link_text, url = extract_markdown_link(detail_cell)
        if not url:
            url = issue_url(source, source_iid)
        rows.append(
            TaskItem(
                key=stable_key_for_table_row(str(source["key"]), source_iid, title, url),
                title=title,
                url=url,
                source=f"{source['name']} SIG table #{source_iid}",
                status=status,
                assignee=assignee,
                sig=sig,
                score=score,
                updated_at=str(source_issue.get("updated_at") or ""),
            )
        )
    return rows


def gitcode_issue_to_task(issue: dict[str, Any], source: dict[str, Any]) -> TaskItem:
    iid = int(issue["iid"])
    labels = ",".join(label_names(issue))
    assignees = issue.get("assignees") or []
    assignee_names = ",".join(str(user.get("username") or user.get("name") or "") for user in assignees)
    return TaskItem(
        key=f"gitcode:{source['key']}:{iid}",
        title=str(issue.get("title") or f"issue #{iid}"),
        url=issue_url(source, iid),
        source=f"{source['name']} issue",
        status=str(issue.get("state") or ""),
        assignee=assignee_names,
        created_at=str(issue.get("created_at") or ""),
        updated_at=str(issue.get("updated_at") or ""),
        labels=labels,
    )


def collect_gitcode_tasks(source: dict[str, Any], include_details: bool = True) -> dict[str, TaskItem]:
    issues = fetch_gitcode_issues(source)
    tasks: dict[str, TaskItem] = {}
    detail_sources: list[dict[str, Any]] = []

    for issue in issues:
        if is_intern_issue(issue, source):
            task = gitcode_issue_to_task(issue, source)
            tasks[task.key] = task
            if should_fetch_issue_detail(issue, source):
                detail_sources.append(issue)

    if include_details and source.get("include_details", True):
        for issue in detail_sources:
            iid = int(issue["iid"])
            try:
                detail = fetch_json(f"{gitcode_issues_api(source)}/{iid}", headers=gitcode_headers(source))
            except Exception as exc:  # noqa: BLE001 - keep one bad issue from stopping notifications
                print(f"warning: failed to fetch {source['name']} issue #{iid}: {exc}", file=sys.stderr)
                continue
            description = str(detail.get("description") or "")
            for table_task in parse_task_table(description, detail, source):
                tasks[table_task.key] = table_task

    return tasks


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Origin": "https://github.com",
        "Referer": "https://github.com/",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def collect_github_tasks(source: dict[str, Any], per_page: int = 100, max_pages: int = 3) -> dict[str, TaskItem]:
    tasks: dict[str, TaskItem] = {}
    repo = str(source["repo"])
    for page in range(1, max_pages + 1):
        payload = fetch_json(
            f"https://api.github.com/repos/{repo}/issues",
            {
                "state": "open",
                "labels": source.get("labels", ""),
                "per_page": per_page,
                "page": page,
            },
            headers=github_headers(),
        )
        if not isinstance(payload, list):
            break
        for issue in payload:
            if "pull_request" in issue:
                continue
            number = int(issue["number"])
            labels = ",".join(str(label.get("name") or "") for label in issue.get("labels") or [])
            assignee_names = ",".join(str(user.get("login") or "") for user in issue.get("assignees") or [])
            task = TaskItem(
                key=f"github:{source['key']}:{number}",
                title=str(issue.get("title") or f"issue #{number}"),
                url=str(issue.get("html_url") or f"{source['web_url']}/{number}"),
                source=f"{source['name']} GitHub issue",
                status=str(issue.get("state") or ""),
                assignee=assignee_names,
                created_at=str(issue.get("created_at") or ""),
                updated_at=str(issue.get("updated_at") or ""),
                labels=labels,
            )
            tasks[task.key] = task
        if len(payload) < per_page:
            break
    return tasks


def collect_tasks(include_details: bool = True) -> list[TaskItem]:
    tasks: dict[str, TaskItem] = {}
    for source in GITCODE_SOURCES:
        try:
            tasks.update(collect_gitcode_tasks(source, include_details=include_details))
        except Exception as exc:  # noqa: BLE001 - keep one source outage from stopping the watcher
            print(f"warning: failed to collect {source['name']} tasks: {exc}", file=sys.stderr)
    for source in GITHUB_SOURCES:
        try:
            tasks.update(collect_github_tasks(source))
        except Exception as exc:  # noqa: BLE001
            print(f"warning: failed to collect {source['name']} tasks: {exc}", file=sys.stderr)
    return sorted(tasks.values(), key=lambda item: (item.created_at or item.updated_at or "", item.key), reverse=True)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "seen": {}, "items": {}, "last_check": None}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def item_snapshot(item: TaskItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["digest"] = item.digest
    payload["claimable"] = item.is_claimable
    return payload


def detect_changes(
    tasks: list[TaskItem],
    state: dict[str, Any],
    notify_existing: bool = False,
    notify_updates: bool = False,
) -> list[tuple[str, TaskItem]]:
    seen: dict[str, str] = state.get("seen") or {}
    previous_items: dict[str, dict[str, Any]] = state.get("items") or {}
    first_run = not seen
    changes: list[tuple[str, TaskItem]] = []

    for item in tasks:
        old_digest = seen.get(item.key)
        if old_digest is None:
            if notify_existing or not first_run:
                if "issue" in item.source.lower():
                    changes.append(("new issue", item))
                elif item.is_claimable:
                    changes.append(("claimable task", item))
            continue
        if old_digest != item.digest:
            old_item = previous_items.get(item.key) or {}
            old_claimable = bool(old_item.get("claimable"))
            if notify_updates or (item.is_claimable and not old_claimable):
                changes.append(("updated task", item))

    return changes


def render_item(item: TaskItem) -> str:
    details = [
        f"- {item.title}",
        f"  URL: {item.url}",
        f"  Source: {item.source}",
    ]
    if item.sig:
        details.append(f"  SIG: {item.sig}")
    if item.score:
        details.append(f"  Score: {item.score}")
    if item.status:
        details.append(f"  Status: {item.status}")
    if item.assignee:
        details.append(f"  Assignee: {item.assignee}")
    return "\n".join(details)


def notify_console(reason: str, item: TaskItem) -> None:
    print(f"\n[{reason}]")
    print(render_item(item))
    try:
        import winsound

        winsound.MessageBeep()
    except Exception:
        pass


def notify_toast(reason: str, item: TaskItem) -> bool:
    try:
        from winotify import Notification
    except Exception:
        return False

    title = "Open source internship task"
    message = f"{reason}: {item.title}"
    toast = Notification(
        app_id="OpenUBMC Task Watcher",
        title=title,
        msg=message[:240],
        duration="long",
    )
    toast.add_actions(label="Open task", launch=item.url)
    toast.show()
    return True


def post_json(url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": DEFAULT_HEADERS["User-Agent"]},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def notify_webhook(webhook_url: str, reason: str, item: TaskItem) -> None:
    post_json(
        webhook_url,
        {
            "source": "openubmc-task-watcher",
            "reason": reason,
            "task": item_snapshot(item),
        },
    )


def notify_server_chan(sendkey: str, reason: str, item: TaskItem) -> None:
    endpoint = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode(
        {
            "title": f"OpenUBMC: {item.title[:80]}",
            "desp": f"Reason: {reason}\n\n{render_item(item)}",
        }
    ).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def notify_pushplus(token: str, reason: str, item: TaskItem) -> None:
    post_json(
        "https://www.pushplus.plus/send",
        {
            "token": token,
            "title": f"OpenUBMC: {item.title[:80]}",
            "content": f"Reason: {reason}\n\n{render_item(item)}",
            "template": "markdown",
        },
    )


def split_recipients(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", value or "") if part.strip()]


def str_to_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def value_from_arg_or_env(args: argparse.Namespace, attr: str, env_name: str, default: str = "") -> str:
    value = getattr(args, attr, "") or os.environ.get(env_name, "")
    return str(value if value is not None else default)


def smtp_config(args: argparse.Namespace) -> dict[str, Any]:
    host = value_from_arg_or_env(args, "smtp_host", "SMTP_HOST")
    port_text = value_from_arg_or_env(args, "smtp_port", "SMTP_PORT")
    port = int(port_text) if port_text else 465
    use_ssl = str_to_bool(value_from_arg_or_env(args, "smtp_ssl", "SMTP_SSL"), default=port == 465)
    starttls = str_to_bool(
        value_from_arg_or_env(args, "smtp_starttls", "SMTP_STARTTLS"),
        default=not use_ssl,
    )
    user = value_from_arg_or_env(args, "smtp_user", "SMTP_USER")
    password = value_from_arg_or_env(args, "smtp_password", "SMTP_PASSWORD")
    sender = value_from_arg_or_env(args, "smtp_from", "SMTP_FROM") or user
    recipients = split_recipients(value_from_arg_or_env(args, "smtp_to", "SMTP_TO"))
    timeout_text = value_from_arg_or_env(args, "smtp_timeout", "SMTP_TIMEOUT")
    timeout = int(timeout_text) if timeout_text else 20
    return {
        "host": host,
        "port": port,
        "ssl": use_ssl,
        "starttls": starttls,
        "user": user,
        "password": password,
        "from": sender,
        "to": recipients,
        "timeout": timeout,
    }


def notify_email(config: dict[str, Any], reason: str, item: TaskItem) -> None:
    missing = [name for name in ("host", "from", "to") if not config.get(name)]
    if missing:
        raise RuntimeError(f"missing SMTP config: {', '.join(missing)}")

    message = EmailMessage()
    message["Subject"] = f"Internship task: {item.title[:90]}"
    message["From"] = config["from"]
    message["To"] = ", ".join(config["to"])
    message.set_content(f"Reason: {reason}\n\n{render_item(item)}\n")

    context = ssl.create_default_context()
    if config["ssl"]:
        with smtplib.SMTP_SSL(
            config["host"],
            config["port"],
            timeout=config["timeout"],
            context=context,
        ) as smtp:
            if config["user"] and config["password"]:
                smtp.login(config["user"], config["password"])
            smtp.send_message(message)
        return

    with smtplib.SMTP(config["host"], config["port"], timeout=config["timeout"]) as smtp:
        if config["starttls"]:
            smtp.starttls(context=context)
        if config["user"] and config["password"]:
            smtp.login(config["user"], config["password"])
        smtp.send_message(message)


def send_notifications(args: argparse.Namespace, changes: list[tuple[str, TaskItem]]) -> None:
    webhook_url = args.webhook_url or os.environ.get("OPENUBMC_WEBHOOK_URL")
    sendkey = args.server_chan_sendkey or os.environ.get("SERVER_CHAN_SENDKEY")
    pushplus_token = args.pushplus_token or os.environ.get("PUSHPLUS_TOKEN")
    email_config = smtp_config(args)

    for reason, item in changes:
        delivered = False

        def deliver(name: str, callback: Any) -> None:
            nonlocal delivered
            try:
                callback()
                delivered = True
            except Exception as exc:  # noqa: BLE001 - one bad channel should not block the rest
                print(f"warning: {name} notification failed: {exc}", file=sys.stderr)

        if "toast" in args.notify:
            delivered = notify_toast(reason, item) or delivered
        if "webhook" in args.notify and webhook_url:
            deliver("webhook", lambda: notify_webhook(webhook_url, reason, item))
        if "serverchan" in args.notify and sendkey:
            deliver("serverchan", lambda: notify_server_chan(sendkey, reason, item))
        if "pushplus" in args.notify and pushplus_token:
            deliver("pushplus", lambda: notify_pushplus(pushplus_token, reason, item))
        if "wechat" in args.notify:
            if sendkey:
                deliver("wechat/serverchan", lambda: notify_server_chan(sendkey, reason, item))
            if pushplus_token:
                deliver("wechat/pushplus", lambda: notify_pushplus(pushplus_token, reason, item))
            if not sendkey and not pushplus_token:
                print("warning: wechat notification skipped: configure SERVER_CHAN_SENDKEY or PUSHPLUS_TOKEN", file=sys.stderr)
        if "email" in args.notify:
            deliver("email", lambda: notify_email(email_config, reason, item))
        if "console" in args.notify or not delivered:
            notify_console(reason, item)


def update_state(path: Path, tasks: list[TaskItem]) -> None:
    state = {
        "version": 1,
        "last_check": utcnow_iso(),
        "seen": {item.key: item.digest for item in tasks},
        "items": {item.key: item_snapshot(item) for item in tasks},
    }
    save_state(path, state)


def print_summary(tasks: list[TaskItem]) -> None:
    issues = [item for item in tasks if "issue" in item.source.lower()]
    claimable = [item for item in tasks if "issue" not in item.source.lower() and item.is_claimable]
    print(f"Collected {len(tasks)} task records: {len(issues)} issue tasks, {len(claimable)} claimable table tasks.")
    if claimable:
        print("\nCurrent claimable table tasks:")
        for item in claimable:
            print(render_item(item))


def run_once(args: argparse.Namespace) -> int:
    if args.test_notify:
        item = TaskItem(
            key="test-notification",
            title=args.test_title,
            url=args.test_url,
            source="notification-test",
            status="test",
            sig="test",
            score="0",
        )
        send_notifications(args, [("test notification", item)])
        print("Test notification completed.")
        return 0

    state_path = Path(args.state)
    old_state = load_state(state_path)
    tasks = collect_tasks(include_details=not args.no_details)

    if args.list:
        print_summary(tasks)

    if args.init:
        update_state(state_path, tasks)
        print(f"Initialized baseline with {len(tasks)} records at {state_path}")
        return 0

    changes = detect_changes(
        tasks,
        old_state,
        notify_existing=args.notify_existing,
        notify_updates=args.notify_updates,
    )
    update_state(state_path, tasks)

    if changes:
        send_notifications(args, changes)
        print(f"Sent {len(changes)} notification(s).")
    else:
        print(f"No new internship task at {utcnow_iso()}. Tracked {len(tasks)} records.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="state.json", help="Path to the local watcher state JSON.")
    parser.add_argument("--env-file", default=os.environ.get("OPENUBMC_ENV_FILE", ".env"), help="Path to a KEY=VALUE env file.")
    parser.add_argument("--once", action="store_true", help="Run one check and exit.")
    parser.add_argument("--loop", action="store_true", help="Run continuously.")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds for --loop.")
    parser.add_argument("--init", action="store_true", help="Save the current tasks as baseline without notifying.")
    parser.add_argument("--list", action="store_true", help="Print a summary of currently discovered tasks.")
    parser.add_argument("--test-notify", action="store_true", help="Send a synthetic notification and exit.")
    parser.add_argument("--test-title", default="Test: OpenUBMC notification channel is working.", help="Title for --test-notify.")
    parser.add_argument("--test-url", default="https://gitcode.com/openUBMC/community/issues", help="URL for --test-notify.")
    parser.add_argument("--notify-existing", action="store_true", help="Notify all currently known tasks on first run.")
    parser.add_argument("--notify-updates", action="store_true", help="Notify any changed tracked task, not only new/claimable.")
    parser.add_argument("--no-details", action="store_true", help="Skip issue detail fetches and table parsing.")
    parser.add_argument(
        "--notify",
        default=os.environ.get("OPENUBMC_NOTIFY", "toast,console"),
        help="Comma-separated notification backends: toast,console,webhook,wechat,serverchan,pushplus,email.",
    )
    parser.add_argument("--webhook-url", default="", help="Generic JSON webhook URL.")
    parser.add_argument("--server-chan-sendkey", default="", help="ServerChan sendkey for WeChat notifications.")
    parser.add_argument("--pushplus-token", default="", help="PushPlus token for WeChat notifications.")
    parser.add_argument("--smtp-host", default="", help="SMTP server host for email notifications.")
    parser.add_argument("--smtp-port", default="", help="SMTP server port, commonly 465 or 587.")
    parser.add_argument("--smtp-user", default="", help="SMTP username.")
    parser.add_argument("--smtp-password", default="", help="SMTP password or app-specific authorization code.")
    parser.add_argument("--smtp-from", default="", help="Sender email address.")
    parser.add_argument("--smtp-to", default="", help="Recipient email address list, separated by comma or semicolon.")
    parser.add_argument("--smtp-ssl", default="", help="Use SMTP over SSL: true/false.")
    parser.add_argument("--smtp-starttls", default="", help="Use STARTTLS: true/false.")
    parser.add_argument("--smtp-timeout", default="", help="SMTP timeout in seconds.")
    args = parser.parse_args(argv)
    args.notify = {item.strip().lower() for item in str(args.notify).split(",") if item.strip()}
    if not args.loop and not args.once:
        args.once = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    load_env_file(args.env_file)
    if args.loop:
        while True:
            try:
                run_once(args)
            except Exception as exc:  # noqa: BLE001 - watcher should survive transient API failures
                print(f"error: {exc}", file=sys.stderr)
            time.sleep(args.interval)
    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
