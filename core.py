import sys_keys
import aiosqlite
import traceback
from typing import Union
import mysql.connector.aio as aiomysql
from datetime import datetime, timedelta
from aiogram.types import Message, CallbackQuery

OWNER = 5128609241
NAME = sys_keys.NAME
mysql = sys_keys.db
release = sys_keys.release
SITE = "https://tgmaksim.ru/проекты/напоминалка"
subscribe = "https://t.me/+toIQibXWy-w1MmVi"
channel = "@MaksimMyBots"

markdown = "Markdown"
html = "HTML"


if release:
    class db:
        @staticmethod
        async def execute(sql: str, params: tuple = tuple()) -> list[tuple]:
            async with await aiomysql.connect(database="c87813_reminder_tgmaksim_ru_reminder", **mysql) as conn:
                async with await conn.cursor() as cur:
                    await cur.execute(sql.replace("?", "%s").replace("key", "`key`"), params)
                    result = await cur.fetchall()
                await conn.commit()
            return result
else:
    class db:
        db_path = "db.sqlite3"

        @staticmethod
        async def execute(sql: str, params: tuple = tuple()) -> tuple[tuple]:
            async with aiosqlite.connect(resources_path(db.db_path)) as conn:
                async with conn.execute(sql, params) as cur:
                    result = await cur.fetchall()
                await conn.commit()
            return result


def security(*arguments):
    def new_decorator(fun):
        async def new(_object: Union[Message, CallbackQuery], **kwargs):
            try:
                await fun(_object, **{kw: kwargs[kw] for kw in kwargs if kw in arguments})
            except Exception as e:
                exception = "".join(traceback.format_exception(e))
                await _object.bot.send_message(OWNER, f"⚠️Ошибка⚠️\n\n{exception}")

        return new

    return new_decorator


def resources_path(path: str) -> str:
    return sys_keys.resources_path(path)


def time_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=6)


def omsk_time(t: datetime):
    tz = int(t.tzinfo.utcoffset(None).total_seconds() // 3600)
    return (t + timedelta(hours=6-tz)).replace(tzinfo=None)


async def get_users() -> set:
    _users = set(map(lambda x: int(x[0]), await db.execute("SELECT id FROM users")))
    return _users


async def get_version():
    return (await db.execute("SELECT value FROM system_data WHERE key=?", ("version",)))[0][0]


async def set_version(version):
    await db.execute("UPDATE system_data SET value=? WHERE key=?", (version, "version"))


async def get_settings():
    return await db.execute("SELECT id, time_zone FROM settings")


async def set_time_zone(id: int, time_zone: str | int):
    now = await db.execute("SELECT id FROM settings WHERE id=?", (id,))
    if now:
        await db.execute("UPDATE settings SET time_zone=? WHERE id=?", (time_zone, id))
    else:
        await db.execute("INSERT INTO settings VALUES (?, ?)", (id, time_zone))
