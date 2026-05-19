import os
import re
import textwrap
from datetime import datetime, timezone

import requests


REPO = os.environ.get("GITHUB_REPOSITORY", "JohanSjoblom/picochess")
OPEN_QUESTIONS_MARKER = "<!-- picochess-issue-agent:open-questions -->"
SPECIFICATION_MARKER = "<!-- picochess-issue-agent:specification -->"


def github_headers():
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_request(method, path, **kwargs):
    url = f"https://api.github.com/repos/{REPO}{path}"
    response = requests.request(method, url, headers=github_headers(), timeout=30, **kwargs)
    response.raise_for_status()
    return response


def parse_github_datetime(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_issue():
    issue_number = os.environ.get("ISSUE_NUMBER", "").strip()
    if issue_number:
        issue = github_request("GET", f"/issues/{issue_number}").json()
        if "pull_request" in issue:
            raise RuntimeError(f"#{issue_number} is a pull request, not an issue")
        return issue

    response = github_request(
        "GET",
        "/issues",
        params={
            "state": "open",
            "sort": "created",
            "direction": "desc",
            "per_page": 20,
        },
    )
    issues = [issue for issue in response.json() if "pull_request" not in issue]
    if not issues:
        raise RuntimeError("No open issues found")
    return issues[0]


def has_any(text, words):
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def format_comment_context(comments):
    if not comments:
        return ""

    blocks = []
    for comment in comments:
        user = (comment.get("user") or {}).get("login") or "unknown"
        body = (comment.get("body") or "").strip()
        if not body:
            continue
        blocks.append(f"{user} commented:\n{body}")
    return "\n\n".join(blocks)


def build_issue_text(issue, comments=None):
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    comment_context = format_comment_context(comments or [])
    if not comment_context:
        return f"{title}\n{body}"
    return f"{title}\n{body}\n\nFollow-up comments:\n{comment_context}"


def build_open_questions(issue, comments=None):
    body = issue.get("body") or ""
    text = build_issue_text(issue, comments).lower()
    body_words = re.findall(r"\w+", f"{body}\n{format_comment_context(comments or [])}")

    questions = []

    if len(body_words) < 25:
        questions.append(
            "Please expand the issue description with the relevant context, current behavior, and desired outcome."
        )

    if not has_any(
        text,
        [
            "current",
            "currently",
            "problem",
            "fail",
            "fails",
            "failure",
            "error",
            "broken",
            "regression",
            "issue",
        ],
    ):
        questions.append("What is the current behavior or problem that needs to be changed?")

    if not has_any(
        text,
        [
            "expected",
            "should",
            "desired",
            "want",
            "needs",
            "goal",
            "fix",
            "solution",
        ],
    ):
        questions.append("What exact behavior should PicoChess have after this issue is fixed?")

    bug_like = has_any(text, ["bug", "error", "fail", "fails", "crash", "traceback", "regression", "broken"])
    if bug_like and not has_any(text, ["steps", "reproduce", "trigger", "when", "after", "before"]):
        questions.append("What are the steps or conditions that reproduce the problem?")

    if not has_any(text, ["test", "verify", "verification", "acceptance", "regression", "works when"]):
        questions.append("How should the finished change be verified?")

    return questions


def build_specification(issue, comments=None):
    title = issue.get("title") or "(untitled issue)"
    body = (issue.get("body") or "").strip()
    number = issue["number"]
    html_url = issue["html_url"]
    comment_context = format_comment_context(comments or [])

    parts = [
        f"# Specification: {title}",
        "",
        f"Source issue: #{number}",
        f"Source URL: {html_url}",
        "",
        "## Issue Description",
        "",
        body,
    ]

    if comment_context:
        parts.extend(["", "## Follow-up Comments", "", comment_context])

    parts.extend(
        [
            "",
            "## Required Behavior",
            "",
            "Implement the behavior described in the source issue.",
            "",
            "## Acceptance Criteria",
            "",
            "- The requested behavior is implemented.",
            "- Existing behavior outside the issue scope is preserved.",
            "- Relevant regression checks pass.",
            "",
            "## Open Questions",
            "",
            "None detected by the issue agent.",
            "",
        ]
    )
    return "\n".join(parts)


def list_issue_comments(issue_number):
    comments = []
    page = 1
    while True:
        response = github_request(
            "GET",
            f"/issues/{issue_number}/comments",
            params={"per_page": 100, "page": page},
        )
        page_comments = response.json()
        comments.extend(page_comments)
        if len(page_comments) < 100:
            return comments
        page += 1


def is_agent_comment(comment):
    user = comment.get("user") or {}
    return user.get("login") == "github-actions[bot]"


def is_agent_metadata_comment(comment):
    body = comment.get("body") or ""
    return is_agent_comment(comment) and (
        OPEN_QUESTIONS_MARKER in body or SPECIFICATION_MARKER in body
    )


def get_latest_agent_metadata_comment(comments):
    agent_comments = [comment for comment in comments if is_agent_metadata_comment(comment)]
    if not agent_comments:
        return None
    return max(agent_comments, key=lambda comment: parse_github_datetime(comment.get("updated_at")))


def get_human_comments_after_latest_agent_metadata(comments):
    latest_agent_comment = get_latest_agent_metadata_comment(comments)
    if not latest_agent_comment:
        return []

    latest_agent_time = parse_github_datetime(latest_agent_comment.get("updated_at"))
    return [
        comment
        for comment in comments
        if not is_agent_comment(comment)
        and parse_github_datetime(comment.get("created_at")) > latest_agent_time
    ]


def find_existing_agent_comment(comments, marker):
    for comment in comments:
        body = comment.get("body") or ""
        if marker in body and is_agent_comment(comment):
            return comment
    return None


def upsert_agent_comment(issue_number, comments, marker, body):
    existing = find_existing_agent_comment(comments, marker)
    if existing:
        github_request("PATCH", f"/issues/comments/{existing['id']}", json={"body": body})
        print(f"Updated existing agent comment on issue #{issue_number}")
        return

    github_request("POST", f"/issues/{issue_number}/comments", json={"body": body})
    print(f"Added agent comment to issue #{issue_number}")


def comment_open_questions(issue, comments, questions):
    question_lines = "\n".join(f"- {question}" for question in questions)
    body = textwrap.dedent(
        f"""\
        {OPEN_QUESTIONS_MARKER}
        Issue Agent could not generate `specification.md` without open questions.

        Please clarify:

        {question_lines}
        """
    )
    upsert_agent_comment(issue["number"], comments, OPEN_QUESTIONS_MARKER, body)


def comment_specification(issue, comments, specification):
    body = (
        f"{SPECIFICATION_MARKER}\n"
        "Issue Agent generated `specification.md` from the current issue description.\n\n"
        "```markdown\n"
        f"{specification.rstrip()}\n"
        "```\n"
    )
    upsert_agent_comment(issue["number"], comments, SPECIFICATION_MARKER, body)


def mark_open_questions_resolved_if_needed(issue, comments):
    existing = find_existing_agent_comment(comments, OPEN_QUESTIONS_MARKER)
    if not existing:
        return
    body = textwrap.dedent(
        f"""\
        {OPEN_QUESTIONS_MARKER}
        Issue Agent generated `specification.md` from the current issue description.

        No open questions were detected by the current checks.
        """
    )
    github_request("PATCH", f"/issues/comments/{existing['id']}", json={"body": body})
    print(f"Marked open-questions comment as resolved on issue #{issue['number']}")


def main():
    issue = get_issue()
    print(f"Checking issue #{issue['number']}: {issue['title']}")
    print(issue["html_url"])

    comments = list_issue_comments(issue["number"])
    followup_comments = get_human_comments_after_latest_agent_metadata(comments)
    if followup_comments:
        print(f"Including {len(followup_comments)} human comment(s) after the latest agent metadata")

    questions = build_open_questions(issue, followup_comments)
    if questions:
        print("Open questions found:")
        for question in questions:
            print(f"- {question}")
        comment_open_questions(issue, comments, questions)
        return

    specification = build_specification(issue, followup_comments)
    with open("specification.md", "w", encoding="utf-8") as spec_file:
        spec_file.write(specification)
    print("Generated specification.md")
    print(specification)
    comment_specification(issue, comments, specification)
    mark_open_questions_resolved_if_needed(issue, comments)


if __name__ == "__main__":
    main()
