import unittest

from tools import issue_agent


def make_comment(body, created_at, user="somebody", updated_at=None):
    return {
        "body": body,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "user": {"login": user},
    }


class TestIssueAgent(unittest.TestCase):

    def test_human_comments_after_latest_agent_metadata_are_used(self):
        comments = [
            make_comment("Earlier discussion", "2026-05-19T10:00:00Z"),
            make_comment(issue_agent.OPEN_QUESTIONS_MARKER, "2026-05-19T11:00:00Z", "github-actions[bot]"),
            make_comment(
                "Current problem: startup fails after engine switch. "
                "Expected behavior should be a clean restart. "
                "Verify by switching engines in PONDER.",
                "2026-05-19T12:00:00Z",
            ),
        ]

        followups = issue_agent.get_human_comments_after_latest_agent_metadata(comments)

        self.assertEqual(1, len(followups))
        self.assertIn("startup fails", followups[0]["body"])

    def test_bot_comments_and_old_human_comments_are_ignored(self):
        comments = [
            make_comment("Old human answer", "2026-05-19T10:00:00Z"),
            make_comment(issue_agent.OPEN_QUESTIONS_MARKER, "2026-05-19T11:00:00Z", "github-actions[bot]"),
            make_comment("Bot follow-up", "2026-05-19T12:00:00Z", "github-actions[bot]"),
        ]

        followups = issue_agent.get_human_comments_after_latest_agent_metadata(comments)

        self.assertEqual([], followups)

    def test_followup_comment_can_satisfy_open_question_checks(self):
        issue = {
            "title": "Engine switch",
            "body": "More details are needed.",
        }
        comment = make_comment(
            "Current problem: switching engines in PONDER leaves stale analysis. "
            "Expected behavior should show the new engine analysis. "
            "Verify by switching engines in PONDER.",
            "2026-05-19T12:00:00Z",
        )

        questions = issue_agent.build_open_questions(issue, [comment])

        self.assertEqual([], questions)

    def test_specification_includes_followup_comments(self):
        issue = {
            "number": 42,
            "title": "Engine switch",
            "body": "Switching engines needs more detail.",
            "html_url": "https://example.com/issues/42",
        }
        comment = make_comment("Expected behavior should show the selected engine.", "2026-05-19T12:00:00Z")

        specification = issue_agent.build_specification(issue, [comment])

        self.assertIn("## Follow-up Comments", specification)
        self.assertIn("somebody commented:", specification)
        self.assertIn("Expected behavior should show the selected engine.", specification)


if __name__ == "__main__":
    unittest.main()
