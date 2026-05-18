import os
import re
import textwrap

import requests


REPO = os.environ.get("GITHUB_REPOSITORY", "JohanSjoblom/picochess")
COMMENT_MARKER = "<!-- picochess-issue-agent:open-questions -->"


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


def build_open_questions(issue):
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    text = f"{title}\n{body}".lower()
    body_words = re.findall(r"\w+", body)

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


def build_specification(issue):
    title = issue.get("title") or "(untitled issue)"
    body = (issue.get("body") or "").strip()
    number = issue["number"]
    html_url = issue["html_url"]

    return textwrap.dedent(
        f"""\
        # Specification: {title}

        Source issue: #{number}
        Source URL: {html_url}

        ## Issue Description

        {body}

        ## Required Behavior

        Implement the behavior described in the source issue.

        ## Acceptance Criteria

        - The requested behavior is implemented.
        - Existing behavior outside the issue scope is preserved.
        - Relevant regression checks pass.

        ## Open Questions

        None detected by the issue agent.
        """
    )


def find_existing_agent_comment(issue_number):
    response = github_request("GET", f"/issues/{issue_number}/comments", params={"per_page": 100})
    for comment in response.json():
        body = comment.get("body") or ""
        user = comment.get("user") or {}
        if COMMENT_MARKER in body and user.get("login") == "github-actions[bot]":
            return comment
    return None


def upsert_agent_comment(issue_number, body):
    existing = find_existing_agent_comment(issue_number)
    if existing:
        github_request("PATCH", f"/issues/comments/{existing['id']}", json={"body": body})
        print(f"Updated existing agent comment on issue #{issue_number}")
        return

    github_request("POST", f"/issues/{issue_number}/comments", json={"body": body})
    print(f"Added agent comment to issue #{issue_number}")


def comment_open_questions(issue, questions):
    question_lines = "\n".join(f"- {question}" for question in questions)
    body = textwrap.dedent(
        f"""\
        {COMMENT_MARKER}
        Issue Agent could not generate `specification.md` without open questions.

        Please clarify:

        {question_lines}
        """
    )
    upsert_agent_comment(issue["number"], body)


def mark_spec_ready_if_needed(issue):
    existing = find_existing_agent_comment(issue["number"])
    if not existing:
        return
    body = textwrap.dedent(
        f"""\
        {COMMENT_MARKER}
        Issue Agent generated `specification.md` from the current issue description.

        No open questions were detected by the current checks.
        """
    )
    github_request("PATCH", f"/issues/comments/{existing['id']}", json={"body": body})
    print(f"Marked existing agent comment as resolved on issue #{issue['number']}")


def main():
    issue = get_issue()
    print(f"Checking issue #{issue['number']}: {issue['title']}")
    print(issue["html_url"])

    questions = build_open_questions(issue)
    if questions:
        print("Open questions found:")
        for question in questions:
            print(f"- {question}")
        comment_open_questions(issue, questions)
        return

    specification = build_specification(issue)
    with open("specification.md", "w", encoding="utf-8") as spec_file:
        spec_file.write(specification)
    print("Generated specification.md")
    print(specification)
    mark_spec_ready_if_needed(issue)


if __name__ == "__main__":
    main()
