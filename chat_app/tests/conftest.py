import pytest
from flask import Flask

from src.models import db


@pytest.fixture
def app(tmp_path):
    application = Flask(__name__)
    db_path = tmp_path / "test.db"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"

    db.init_app(application)
    with application.app_context():
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()
