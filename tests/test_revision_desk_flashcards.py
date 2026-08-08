from pathlib import Path
import unittest


class RevisionDeskFlashcardsTests(unittest.TestCase):
    def test_revision_desk_template_supports_flashcard_attachments(self):
        template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "revision_desk.html"
        content = template_path.read_text(encoding="utf-8")

        self.assertIn("Attachments", content)
        self.assertIn("setFlashcardDetails", content)
        self.assertIn("attachments-", content)
        self.assertIn("type=\"file\"", content)
        self.assertIn("uploadAttachment", content)
        self.assertIn("/revision-desk/attachments/upload", content)
        self.assertIn("Test score", content)
        self.assertIn("Max marks", content)
        self.assertIn("IB score", content)
        self.assertIn("setMaxMarks", content)
        self.assertIn("safeCalculateIBGrade", content)
        self.assertIn("openChapterHistory", content)
        self.assertIn("const ACTIVE_TAB_KEY", content)
        self.assertIn("localStorage.setItem(ACTIVE_TAB_KEY, tab)", content)
        self.assertIn("function setTab(tab)", content)
        self.assertIn("/logout", content)

    def test_login_template_allows_study_mate_or_revision_desk(self):
        template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "login.html"
        content = template_path.read_text(encoding="utf-8")

        self.assertIn('name="next" value="{{ next }}"', content)
        self.assertIn('onclick="setLoginNext(\'/\')"', content)
        self.assertIn('onclick="setLoginNext(\'/revision-desk\')"', content)
        self.assertIn('id="login-form"', content)


if __name__ == "__main__":
    unittest.main()
