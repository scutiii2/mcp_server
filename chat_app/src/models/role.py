from src.models.associations import account_role, role_permission
from src.models.base import db


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    accounts = db.relationship("Account", secondary=account_role, back_populates="roles")
    permissions = db.relationship("Permission", secondary=role_permission, back_populates="roles")
