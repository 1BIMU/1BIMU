#!/usr/bin/env python3
"""Auto-update README.md with pinned repos, recent activity, and blog posts."""

import os
import re
import sys
from datetime import datetime, timezone

import requests

# ── Config ────────────────────────────────────────────────────────────────────
USERNAME = "1BIMU"
README_PATH = "README.md"

# Optional: set this to your blog's RSS/Atom feed URL to enable blog posts.
# Leave empty to skip the blog section.
BLOG_RSS_URL = os.environ.get("BLOG_RSS_URL", "")

TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
GRAPHQL_URL = "https://api.github.com/graphql"
# ──────────────────────────────────────────────────────────────────────────────


def fetch_pinned_repos() -> list[dict]:
    query = """
    {
      user(login: "%s") {
        pinnedItems(first: 6, types: [REPOSITORY]) {
          nodes {
            ... on Repository {
              name
              description
              url
              stargazerCount
              forkCount
              primaryLanguage { name color }
              updatedAt
            }
          }
        }
      }
    }
    """ % USERNAME
    resp = requests.post(GRAPHQL_URL, json={"query": query}, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        print("GraphQL errors:", data["errors"], file=sys.stderr)
        return []
    return data["data"]["user"]["pinnedItems"]["nodes"]


def fetch_recent_activity(limit: int = 5) -> list[dict]:
    url = f"https://api.github.com/users/{USERNAME}/events?per_page=100"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    events = resp.json()

    results = []
    seen_repos = set()
    for event in events:
        etype = event.get("type", "")
        repo = event.get("repo", {}).get("name", "")
        if etype == "PushEvent" and repo not in seen_repos:
            commits = event.get("payload", {}).get("commits", [])
            if commits:
                msg = commits[-1].get("message", "").split("\n")[0][:80]
                results.append({
                    "type": "push",
                    "repo": repo,
                    "message": msg,
                    "created_at": event["created_at"],
                })
                seen_repos.add(repo)
        elif etype == "CreateEvent" and repo not in seen_repos:
            ref_type = event.get("payload", {}).get("ref_type", "")
            if ref_type == "repository":
                results.append({
                    "type": "create",
                    "repo": repo,
                    "message": "Created repository",
                    "created_at": event["created_at"],
                })
                seen_repos.add(repo)
        if len(results) >= limit:
            break
    return results


def fetch_blog_posts(rss_url: str, limit: int = 5) -> list[dict]:
    """Fetch latest posts from an RSS/Atom feed."""
    try:
        import feedparser  # type: ignore
    except ImportError:
        print("feedparser not installed; skipping blog.", file=sys.stderr)
        return []
    feed = feedparser.parse(rss_url)
    posts = []
    for entry in feed.entries[:limit]:
        posts.append({
            "title": entry.get("title", "Untitled"),
            "link": entry.get("link", ""),
            "date": entry.get("published", "")[:10],
        })
    return posts


# ── Renderers ─────────────────────────────────────────────────────────────────

def render_pinned_repos(repos: list[dict]) -> str:
    if not repos:
        return "_No pinned repositories found._"
    lines = []
    for repo in repos:
        name = repo["name"]
        desc = (repo.get("description") or "").strip()
        url = repo["url"]
        stars = repo["stargazerCount"]
        forks = repo["forkCount"]
        lang_info = repo.get("primaryLanguage")

        lang_badge = ""
        if lang_info:
            lang_name = lang_info["name"]
            color = lang_info["color"].lstrip("#") if lang_info.get("color") else "888"
            safe = lang_name.replace("-", "--").replace(" ", "_")
            lang_badge = f"![{lang_name}](https://img.shields.io/badge/-{safe}-{color}?style=flat-square&logoColor=white)"

        lines.append(
            f"**[{name}]({url})**"
            + (f" — {desc}" if desc else "")
        )
        meta = []
        if lang_badge:
            meta.append(lang_badge)
        meta.append(f"⭐ {stars}")
        meta.append(f"🍴 {forks}")
        lines.append("  ".join(meta))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_recent_activity(events: list[dict]) -> str:
    if not events:
        return "_No recent public activity._"
    lines = []
    for ev in events:
        repo = ev["repo"]
        msg = ev["message"]
        date = ev["created_at"][:10]
        repo_url = f"https://github.com/{repo}"
        lines.append(f"- `{date}` [{repo}]({repo_url}) — {msg}")
    return "\n".join(lines)


def render_blog_posts(posts: list[dict]) -> str:
    if not posts:
        return "_Blog RSS not configured or no posts found. Set `BLOG_RSS_URL` to enable._"
    lines = []
    for post in posts:
        lines.append(f"- `{post['date']}` [{post['title']}]({post['link']})")
    return "\n".join(lines)


# ── README patcher ─────────────────────────────────────────────────────────────

def patch_section(content: str, tag: str, new_body: str) -> str:
    start_tag = f"<!-- {tag}_START -->"
    end_tag = f"<!-- {tag}_END -->"
    pattern = re.compile(
        rf"{re.escape(start_tag)}.*?{re.escape(end_tag)}",
        re.DOTALL,
    )
    replacement = f"{start_tag}\n{new_body}\n{end_tag}"
    updated, n = pattern.subn(replacement, content)
    if n == 0:
        print(f"Warning: tag {tag} not found in README.", file=sys.stderr)
    return updated


def main() -> None:
    with open(README_PATH, encoding="utf-8") as f:
        readme = f.read()

    print("Fetching pinned repos...")
    pinned = fetch_pinned_repos()
    print(f"  Found {len(pinned)} pinned repos.")

    print("Fetching recent activity...")
    activity = fetch_recent_activity()
    print(f"  Found {len(activity)} events.")

    blog_posts: list[dict] = []
    if BLOG_RSS_URL:
        print(f"Fetching blog posts from {BLOG_RSS_URL}...")
        blog_posts = fetch_blog_posts(BLOG_RSS_URL)
        print(f"  Found {len(blog_posts)} posts.")
    else:
        print("BLOG_RSS_URL not set; skipping blog section.")

    readme = patch_section(readme, "PINNED_REPOS", render_pinned_repos(pinned))
    readme = patch_section(readme, "RECENT_ACTIVITY", render_recent_activity(activity))
    readme = patch_section(readme, "BLOG", render_blog_posts(blog_posts))

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"README updated at {now}")


if __name__ == "__main__":
    main()
