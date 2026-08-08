from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


PR_URL_PATTERN = re.compile(r"^/([^/]+)/([^/]+)/pull/(\d+)/?$")


@dataclass(frozen=True)
class GitHubPullRequest:
    owner: str
    repo: str
    number: int
    url: str

    @property
    def api_prefix(self) -> str:
        return f"repos/{quote(self.owner)}/{quote(self.repo)}/pulls/{self.number}"

    @property
    def issue_comments_path(self) -> str:
        return f"repos/{quote(self.owner)}/{quote(self.repo)}/issues/{self.number}/comments"


class GitHubClient:
    def __init__(self, token: str | None = None, api_base: str | None = None):
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.api_base = (api_base or os.getenv("GITHUB_API_BASE", "https://api.github.com")).rstrip("/")

    def get_pull_request(self, pull: GitHubPullRequest) -> dict[str, object]:
        return self._request("GET", f"/{pull.api_prefix}")

    def get_pull_diff(self, pull: GitHubPullRequest) -> tuple[list[str], str]:
        metadata = self.get_pull_request(pull)
        files = [str(item.get("filename")) for item in metadata.get("changed_files_detail", []) if isinstance(item, dict)]
        if not files:
            files = [str(item) for item in metadata.get("changed_files_list", [])]
        diff = self._request_text("GET", f"/{pull.api_prefix}.diff", accept="application/vnd.github.v3.diff")
        # The metadata endpoint normally exposes changed_files as a count only;
        # parse names from the diff when the file list endpoint is not used.
        if not files:
            files = _diff_file_names(diff)
        return files, diff

    def post_pr_comment(self, pull: GitHubPullRequest, body: str) -> dict[str, object]:
        return self._request("POST", f"/{pull.issue_comments_path}", {"body": body[:60000]})

    def upsert_pr_comment(self, pull: GitHubPullRequest, body: str, marker: str) -> dict[str, object]:
        comments = self._request("GET", f"/{pull.issue_comments_path}?per_page=100")
        if isinstance(comments, list):
            for comment in comments:
                if isinstance(comment, dict) and marker in str(comment.get("body") or ""):
                    comment_id = comment.get("id")
                    if comment_id:
                        return self._request("PATCH", f"/repos/{quote(pull.owner)}/{quote(pull.repo)}/issues/comments/{comment_id}", {"body": body[:60000]})
        return self.post_pr_comment(pull, body)

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "DevAgent-Studio/0.2", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None):
        request = Request(
            f"{self.api_base}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={**self._headers(), "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"GitHub API request failed: {getattr(exc, 'code', '')} {exc}") from exc
        return json.loads(data) if data else {}

    def _request_text(self, method: str, path: str, accept: str) -> str:
        request = Request(f"{self.api_base}{path}", headers=self._headers(accept), method=method)
        try:
            with urlopen(request, timeout=15) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"GitHub diff request failed: {getattr(exc, 'code', '')} {exc}") from exc


def parse_pull_request_url(url: str) -> GitHubPullRequest:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Only GitHub pull request URLs are supported")
    match = PR_URL_PATTERN.match(parsed.path)
    if not match:
        raise ValueError("Expected URL format: https://github.com/{owner}/{repo}/pull/{number}")
    return GitHubPullRequest(match.group(1), match.group(2), int(match.group(3)), url.strip())


def verify_webhook_signature(body: bytes, signature: str | None, secret: str | None = None) -> bool:
    configured = secret or os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not configured or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(configured.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _diff_file_names(diff: str) -> list[str]:
    names: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            name = line[6:].strip()
            if name != "/dev/null" and name not in names:
                names.append(name)
    return names
