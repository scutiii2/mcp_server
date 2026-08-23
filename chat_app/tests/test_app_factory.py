from flask import Flask

from src.models import Account, db
from src.run import BASE_DIR, create_app


def test_create_app_returns_flask_app(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    assert isinstance(app, Flask)
    assert app.config["SQLALCHEMY_DATABASE_URI"] == f"sqlite:///{tmp_path / 'test.db'}"


def test_create_app_initializes_tables(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    with app.app_context():
        account = Account(username="dave", email="dave@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        fetched = db.session.query(Account).filter_by(username="dave").one()
        assert fetched.email == "dave@example.com"


def test_create_app_has_secret_key_set(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    assert app.config["SECRET_KEY"]


def test_create_app_ensures_data_dir_exists(tmp_path):
    create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    assert (BASE_DIR / "data").is_dir()
