"""Publish OSI + ODCS YAML files to a GitHub contracts repo.

Each publish is a sequence of `PUT /repos/{owner}/{repo}/contents/{path}`
calls — one per file. The publisher GETs the file first to discover its
current SHA (needed for update); a 404 means the file is new and the PUT
omits the SHA.

Configuration is via environment:

  - GITHUB_CONTRACTS_REPO   "<owner>/<repo>" of the contracts repo
  - GITHUB_BRANCH           default "main"
  - GITHUB_TOKEN            PAT with `contents:write` on the repo
  - GITHUB_AUTHOR_EMAIL     optional commit author email
  - GITHUB_AUTHOR_NAME      optional commit author name

If GITHUB_TOKEN is not set, `publish()` returns a dry-run result that
records the files that would have been written. The caller (the producer
service) still persists the new model to the local store in either case
so the portal can browse it immediately.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


GITHUB_API = "https://api.github.com"


def _creds() -> dict[str, Any] | None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_CONTRACTS_REPO")
    if not (token and repo):
        return None
    return {
        "token": token,
        "repo": repo,
        "branch": os.environ.get("GITHUB_BRANCH", "main"),
        "author_email": os.environ.get("GITHUB_AUTHOR_EMAIL", "osi-bridge@databricks.com"),
        "author_name": os.environ.get("GITHUB_AUTHOR_NAME", "OSI Bridge"),
    }


def publish(files: dict[str, str], *, commit_message: str, dry_run: bool = False) -> dict[str, Any]:
    """Publish a mapping `{repo_path: file_content}`. Returns a result with
    per-file status and (when live) commit SHA + html_url. `dry_run=True`
    forces the no-credentials path."""
    creds = None if dry_run else _creds()
    results: list[dict[str, Any]] = []
    if creds is None:
        for path, content in files.items():
            results.append({
                "path": path,
                "status": "dry-run",
                "detail": f"Would commit {len(content)} bytes to {path}",
            })
        return {"mode": "dry-run", "files": results, "commit_message": commit_message}

    for path, content in files.items():
        results.append(_put_file(creds, path, content, commit_message))
    return {"mode": "live", "files": results, "commit_message": commit_message}


def _put_file(creds: dict[str, Any], path: str, content: str, commit_message: str) -> dict[str, Any]:
    repo = creds["repo"]
    branch = creds["branch"]
    token = creds["token"]
    encoded = base64.b64encode(content.encode()).decode()
    existing_sha = _existing_sha(repo, path, branch, token)

    body: dict[str, Any] = {
        "message": commit_message,
        "content": encoded,
        "branch": branch,
        "committer": {"name": creds["author_name"], "email": creds["author_email"]},
    }
    if existing_sha:
        body["sha"] = existing_sha

    url = f"{GITHUB_API}/repos/{repo}/contents/{urllib.parse.quote(path)}"
    req = urllib.request.Request(
        url,
        method="PUT",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "osi-bridge",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        commit = data.get("commit") or {}
        return {
            "path": path,
            "status": "committed",
            "sha": (data.get("content") or {}).get("sha"),
            "html_url": commit.get("html_url"),
            "commit_sha": commit.get("sha"),
        }
    except urllib.error.HTTPError as e:
        return {
            "path": path,
            "status": "failed",
            "detail": f"HTTP {e.code}: {e.read().decode()[:200]}",
        }
    except Exception as e:
        return {"path": path, "status": "failed", "detail": f"{type(e).__name__}: {e}"}


def _existing_sha(repo: str, path: str, branch: str, token: str) -> str | None:
    url = f"{GITHUB_API}/repos/{repo}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "osi-bridge",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("sha")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
