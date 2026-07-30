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


if __name__ == "__main__":
    unittest.main()
