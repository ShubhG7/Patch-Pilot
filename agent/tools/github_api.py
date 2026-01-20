from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


class GitHubAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubAPI:
    repo_full_name: str  # owner/name
    token: str
    api_base: str = "https://api.github.com"
    timeout_s: int = 30

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PatchPilot-Demo",
        }

    def _req(self, method: str, path: str, *, json_body: dict | None = None) -> Any:
        url = f"{self.api_base}{path}"
        resp = requests.request(
            method,
            url,
            headers=self._headers(),
            json=json_body,
            timeout=self.timeout_s,
        )
        if resp.status_code >= 400:
            raise GitHubAPIError(f"GitHub API {method} {path} -> {resp.status_code}: {resp.text[:500]}")
        if resp.text.strip():
            return resp.json()
        return {}

    def get_repo(self) -> dict[str, Any]:
        return self._req("GET", f"/repos/{self.repo_full_name}")

    def get_issue(self, issue_number: int) -> dict[str, Any]:
        return self._req("GET", f"/repos/{self.repo_full_name}/issues/{issue_number}")

    def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        data = self._req("GET", f"/repos/{self.repo_full_name}/issues/{issue_number}/comments")
        if not isinstance(data, list):
            raise GitHubAPIError("Unexpected response for list comments")
        return data

    def post_issue_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        return self._req(
            "POST",
            f"/repos/{self.repo_full_name}/issues/{issue_number}/comments",
            json_body={"body": body},
        )

    def create_pull_request(self, *, title: str, head: str, base: str, body: str) -> dict[str, Any]:
        return self._req(
            "POST",
            f"/repos/{self.repo_full_name}/pulls",
            json_body={"title": title, "head": head, "base": base, "body": body},
        )


def from_env(repo_full_name: str) -> GitHubAPI:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubAPIError("Missing GITHUB_TOKEN")
    return GitHubAPI(repo_full_name=repo_full_name, token=token)

