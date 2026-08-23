from src.models.associations import role_permission
from src.models.base import db


class Permission(db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    roles = db.relationship("Role", secondary=role_permission, back_populates="permissions")
