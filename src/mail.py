from sqlalchemy import Column, Integer, String

from src.db_session import SqlAlchemyBase


class Mail(SqlAlchemyBase):
    __tablename__ = 'mail'

    user_id = Column(Integer, primary_key=True, unique=True)
    ads = Column(String, nullable=True)