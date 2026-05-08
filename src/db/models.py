from sqlmodel import SQLModel, Field
from sqlalchemy import BigInteger, Column, Text
from typing import Optional
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc)


class UserInfo(SQLModel, table=True):
    __tablename__ = "users"

    user_id: int = Field(sa_column=Column(BigInteger(), primary_key=True,))
    user_name: Optional[str] = Field(default=None)


class OrdersHistory(SQLModel, table=True):
    __tablename__ = "orders_history"

    order_id: int = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    user_id: int = Field(sa_column=Column(BigInteger()))
    steam_login: str = Field(default=None)
    amount: int = Field(default=None)
    status: str = Field(default="Создан")
    dessly_order_id: Optional[str] = Field(default=None)