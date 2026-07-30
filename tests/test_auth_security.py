import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import auth, config
from app.db import Base


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        config.get_settings.cache_clear()

    def tearDown(self):
        config.get_settings.cache_clear()

    def _create_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        engine = create_engine(f"sqlite:///{Path(temp_dir.name) / 'test.db'}")
        Base.metadata.create_all(engine)
        session = Session(engine)
        self.addCleanup(session.close)
        self.addCleanup(engine.dispose)
        return session

    def test_ensure_admin_user_uses_env_password_when_provided(self):
        with patch.dict(os.environ, {"STUDYMATE_ADMIN_PASSWORD": "Sup3rSecure!123"}, clear=False):
            with self._create_session() as session:
                user = auth.ensure_admin_user(session)
                self.assertTrue(auth.verify_password("Sup3rSecure!123", user.password_hash))
                self.assertFalse(auth.verify_password("admin", user.password_hash))

    def test_secret_is_not_derived_from_database_url(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as handle:
            secret_path = handle.name
        self.addCleanup(lambda: os.remove(secret_path) if os.path.exists(secret_path) else None)

        with patch.dict(os.environ, {
            "DATABASE_URL": "sqlite:////tmp/insecure.db",
            "STUDYMATE_SECRET_FILE": secret_path,
        }, clear=True):
            secret = auth._secret()

        self.assertNotEqual(secret, b"sqlite:////tmp/insecure.db::studymate")
        self.assertTrue(secret)


if __name__ == "__main__":
    unittest.main()
