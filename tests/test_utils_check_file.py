import os
import time
import unittest
from pathlib import Path

from utils import check_file


class TestCheckFileLogic(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(self._testMethodName)
        self.test_dir.mkdir(exist_ok=True)

    def tearDown(self):
        for child in self.test_dir.iterdir():
            if child.is_file():
                child.unlink()
        self.test_dir.rmdir()

    def _create_file(self, name: str, days_old: int = 0) -> Path:
        file_path = self.test_dir / name
        file_path.write_text("data", encoding="utf-8")
        if days_old > 0:
            seconds_old = days_old * 24 * 60 * 60
            past_time = time.time() - seconds_old
            os.utime(file_path, (past_time, past_time))
        return file_path

    def test_or_logic_matches_age_even_when_pattern_fails(self):
        file_path = self._create_file("sample.txt", days_old=2)
        result = check_file(file_path, age_days=1, pattern="*.nomatch", use_regex=False, rule_logic="OR")
        self.assertTrue(result)

    def test_or_logic_matches_pattern_even_when_age_fails(self):
        file_path = self._create_file("keep_me.txt", days_old=0)
        result = check_file(file_path, age_days=10, pattern="*.txt", use_regex=False, rule_logic="OR")
        self.assertTrue(result)

    def test_and_logic_requires_both_conditions(self):
        file_path = self._create_file("target.log", days_old=5)
        self.assertTrue(check_file(file_path, age_days=2, pattern="*.log", use_regex=False, rule_logic="AND"))
        self.assertFalse(check_file(file_path, age_days=2, pattern="*.txt", use_regex=False, rule_logic="AND"))
        self.assertFalse(check_file(file_path, age_days=10, pattern="*.log", use_regex=False, rule_logic="AND"))


if __name__ == "__main__":
    unittest.main()
