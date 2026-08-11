from pathlib import Path
import unittest


class StudyPlannerFeatureTests(unittest.TestCase):
    def test_study_planner_template_includes_required_views_and_sections(self):
        template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "study_planner.html"
        content = template_path.read_text(encoding="utf-8")

        self.assertIn("Daily Timeline", content)
        self.assertIn("Weekly Grid", content)
        self.assertIn("Weekly subject time totals", content)
        self.assertIn("Add to today's plan", content)
        self.assertIn("Pull due cards for this subject", content)
        self.assertIn("Streak:", content)
        self.assertIn("Fixed", content)

    def test_main_registers_study_planner_routes(self):
        main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
        content = main_path.read_text(encoding="utf-8")

        self.assertIn('@app.get("/study-planner"', content)
        self.assertIn('@app.post("/study-planner/blocks/{block_id}/toggle"', content)
        self.assertIn('@app.post("/study-planner/blocks/{block_id}/move"', content)
        self.assertIn('@app.post("/study-planner/add-due"', content)

    def test_study_planner_logic_has_ucat_rotation_and_intervals(self):
        planner_path = Path(__file__).resolve().parents[1] / "app" / "study_planner.py"
        content = planner_path.read_text(encoding="utf-8")

        self.assertIn("REVISION_INTERVALS = [2, 4, 7, 14, 30]", content)
        self.assertIn("UCAT: Verbal Reasoning", content)
        self.assertIn("UCAT: Decision Making", content)
        self.assertIn("UCAT: Quantitative Reasoning", content)
        self.assertIn("UCAT: Abstract Reasoning", content)
        self.assertIn("UCAT: Situational Judgement", content)


if __name__ == "__main__":
    unittest.main()
