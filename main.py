import re
import sys
import json
import string
import asyncio
import aiohttp
from typing import Literal
from sys_keys import TOKEN, api_key, process_id
from datetime import datetime, timedelta
from core import (
    db,
    html,
    NAME,
    SITE,
    OWNER,
    channel,
    security,
    markdown,
    time_now,
    subscribe,
    omsk_time,
    get_users,
    get_version,
    set_version,
    get_settings,
    set_time_zone,
    resources_path,
)

from aiogram import Bot, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters.command import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup as IMarkup
from aiogram.types import InlineKeyboardButton as IButton
from aiogram.types import (
    Message,
    WebAppInfo,
    FSInputFile,
    CallbackQuery,
    MessageEntity,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

bot = Bot(TOKEN)
dp = Dispatcher()


# Класс напоминания
class Reminder:
    printable = string.printable + "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"

    def __init__(self, id: int, chat_id: int, text: str, time: datetime,
                 str_time: str, frequency: str, entities: list[MessageEntity], publish: bool, parent: int):
        self.id = id
        self.chat_id = chat_id
        self.text = text
        self.time = time
        self.str_time = str_time
        self.frequency = frequency
        self.entities = entities
        self.publish = publish
        self.parent = parent

    def __call__(self) -> bool:
        if not self.frequency:
            return time_now() >= self.time
        now = time_now()
        match self.frequency:
            case "day":
                return (now.hour, now.minute) == (self.time.hour, self.time.minute)
            case "week":
                return (now.weekday(), now.hour, now.minute) == \
                    (self.time.weekday(), self.time.hour, self.time.minute)
            case "month":
                return (now.day, now.hour, now.minute) == (self.time.day, self.time.hour, self.time.minute)
        return False

    def my_reminders(self, time_zone: int) -> str:
        time_reminder = self.time + timedelta(hours=time_zone - 6)
        str_time = time_reminder.__str__()
        buttons = f"<a href='t.me/{NAME}?start=delete_reminder_{self.id}'>Удалить</a>"
        if self.publish:
            buttons += f" / <a href='t.me/{NAME}?start=edit_reminder_{self.id}'>Изменить</a>"
            buttons += f"\n<a href='tg://msg_url?url=t.me/{NAME}?start=new_reminder_{self.id}&" \
                       f"text=Я+делюсь+с+тобой+напоминанием'>Поделиться</a>"
        elif self.parent == -1:
            buttons += f" / <a href='t.me/{NAME}?start=edit_reminder_{self.id}'>Изменить</a>"
            if not self.frequency:
                buttons += f"\n<a href='t.me/{NAME}?start=set_publish_{self.id}'>Сделать открытым</a>"
        frequency = f"\nЧастота: {Data.text_frequency[self.frequency].lower()}" if self.frequency else ""
        publish = "\n❗️Публичное❗️" if self.publish else ""
        text = f"Текст: {self.text}\nВремя: {str_time}{frequency}{publish}\n{buttons}"
        return text


# Класс пользовательских настроек
class Settings:
    def __init__(self, id: int, time_zone: str):
        self.id = id
        self.time_zone = time_zone

    @staticmethod
    def load_settings(data: tuple[tuple[str, ...], ...]):
        clients_settings = {}
        for client in data:
            clients_settings[int(client[0])] = Settings(int(client[0]), *client[1:])
        return clients_settings

    @staticmethod
    def default(id: int):
        return Settings(id, "6")


# Класс с глобальными переменными для удобного пользования
class Data:
    url_select_datetime = "https://tgmaksim.ru/reminder_maksim_bot_select/datetime?time_zone="
    url_select_time = "https://tgmaksim.ru/reminder_maksim_bot_select/time?time_zone="
    users = set()
    settings: dict[int, Settings] = {}
    reminders: list[Reminder] = []
    text_frequency = {"day": "Каждый день", "week": "Каждую неделю", "month": "Каждый месяц"}
    text_replay = {"5minutes": "через 5 минут", "hour": "через час", "day": "через день", "week": "через неделю"}
    frequency_reminders = (
        ("Каждый день", "day"),
        ("Каждую неделю", "week"),
        ("Каждый месяц", "month"),
    )


# Класс нужен для определения состояния пользователя в данном боте,
# например: пользователь должен отправить отзыв в следующем сообщении
class UserState(StatesGroup):
    review = State('review')

    create_new_reminder = State('create_new_reminder')
    create_new_often_reminder = State('create_new_often_reminder')

    text_new_reminder = State('text_new_reminder')
    text_new_often_reminder = State('text_new_often_reminder')

    time_new_often_reminder = State('time_new_often_reminder')

    select_time_zone = State('select_time_zone')
    edit_reminder = State('edit_reminder')
    set_publish = State('set_publish')


# Метод для отправки сообщения от имени бота
@dp.message(F.reply_to_message.__and__(F.chat.id == OWNER).__and__(F.reply_to_message.text.startswith("ID")))
@security()
async def _sender(message: Message):
    user_id = int(message.reply_to_message.text.split('\n', 1)[0].replace("ID: ", ""))
    try:
        copy_message = await bot.copy_message(user_id, OWNER, message.message_id)
    except Exception as e:
        await message.answer(f"Сообщение не отправлено из-за ошибки {e.__class__.__name__}: {e}")
    else:
        await message.answer("Сообщение отправлено")
        await bot.forward_message(OWNER, user_id, copy_message.message_id)


@dp.message(Command('admin'))
@security()
async def _admin(message: Message):
    if await developer_command(message): return
    await message.answer("Команды разработчика:\n"
                         "/reload - перезапустить бота\n"
                         "/stop - остановить бота\n"
                         "/db - база данных бота\n"
                         "/all_reminders - все активные напоминания\n"
                         "/version - изменить версию бота\n"
                         "/new_acquaintance - добавить знакомого")


@dp.message(Command('reload'))
@security()
async def _reload(message: Message):
    if await developer_command(message): return
    await message.answer(f"*Перезапуск бота*", parse_mode=markdown)
    print("Перезапуск бота")
    if sys.argv[1] == "release":
        await dp.stop_polling()
        asyncio.get_event_loop().stop()  # netangels после остановки фонового процесса автоматически запустит его
    else:
        await dp.stop_polling()
        asyncio.get_event_loop().stop()


@dp.message(Command('stop'))
@security()
async def _stop(message: Message):
    if await developer_command(message): return
    await message.answer("*Остановка бота*", parse_mode=markdown)
    print("Остановка бота")
    if sys.argv[1] == "release":
        async with aiohttp.ClientSession() as session:
            async with session.post("https://panel.netangels.ru/api/gateway/token/",
                                    data={"api_key": api_key}) as response:
                token = (await response.json())['token']
                await session.post(f"https://api-ms.netangels.ru/api/v1/hosting/background-processes/{process_id}/stop",
                                   headers={"Authorization": f"Bearer {token}"})
    else:
        await dp.stop_polling()
        asyncio.get_event_loop().stop()


@dp.message(Command('db'))
@security()
async def _db(message: Message):
    if await developer_command(message): return
    await message.answer_document(FSInputFile(resources_path(db.db_path)))


@dp.message(Command('new_acquaintance'))
@security()
async def _new_acquaintance(message: Message):
    if await developer_command(message): return
    if message.reply_to_message and message.reply_to_message.caption:
        id = int(message.reply_to_message.caption.split('\n', 1)[0].replace("ID: ", ""))
        name = message.text.split(maxsplit=1)[1]
    else:
        id, name = message.text.split(maxsplit=2)[1:]
    if await db.execute("SELECT id FROM acquaintances WHERE id=?", (id,)):
        await db.execute("UPDATE acquaintances SET name=? WHERE id=?", (name, id))
        await message.answer("Данные знакомого изменены")
    else:
        await db.execute("INSERT INTO acquaintances VALUES(?, ?)", (id, name))
        await message.answer("Добавлен новый знакомый!")


@dp.message(Command('all_reminders'))
@security()
async def _all_reminders(message: Message):
    if await developer_command(message): return
    user_reminders = []
    for reminder in Data.reminders:
        user_reminders.append(reminder.my_reminders(6))
    if not user_reminders:
        return await message.answer("У меня нет активных напоминаний")
    text = "\n\n".join(map(lambda x: x, user_reminders))
    await message.answer(text=text, parse_mode=html)


@dp.message(Command('review'))
@security('state')
async def _start_review(message: Message, state: FSMContext):
    if await new_message(message): return
    await state.set_state(UserState.review)
    markup = IMarkup(inline_keyboard=[[IButton(text="❌", callback_data="stop_review")]])
    await message.answer("Отправьте текст вопроса или предложения. Любое следующее сообщение будет считаться отзывом",
                         reply_markup=markup)


@dp.message(UserState.review)
@security('state')
async def _review(message: Message, state: FSMContext):
    if await new_message(message, False): return
    await state.clear()
    acquaintance = await username_acquaintance(message)
    acquaintance = f"<b>Знакомый: {acquaintance}</b>\n" if acquaintance else ""
    await bot.send_photo(OWNER,
                         photo=FSInputFile(resources_path("resources/reviews.png")),
                         caption=f"ID: {message.chat.id}\n"
                            f"{acquaintance}" +
                            (f"USERNAME: @{message.from_user.username}\n" if message.from_user.username else "") +
                            f"Имя: {message.from_user.first_name}\n" +
                            (f"Фамилия: {message.from_user.last_name}\n" if message.from_user.last_name else "") +
                            f"Время: {omsk_time(message.date)}",
                         parse_mode=html)
    await message.forward(OWNER)
    await message.answer("Большое спасибо за отзыв!❤️❤️❤️")


@dp.callback_query(F.data == "stop_review")
@security('state')
async def _stop_review(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Стоп отправке отзыва"): return
    await state.clear()
    await callback_query.message.edit_text("Отправка отзыва отменена")


@dp.message(Command('version'))
@security()
async def _version(message: Message):
    if message.text != '/version':
        if await developer_command(message): return
        version = message.text.split(" ", 1)[1]
        await set_version(version)
        await message.answer("Версия бота изменена")
    else:
        if await new_message(message): return
        version = await get_version()
        await message.answer(f"Версия: {version}\n<a href='{SITE}/{version}'>Обновление</a> 👇", parse_mode=html)


@dp.callback_query(F.data == 'subscribe')
@security()
async def _check_subscribe(callback_query: CallbackQuery):
    if await new_callback_query(callback_query, "Вроде подписан"): return
    if (await bot.get_chat_member(channel, callback_query.message.chat.id)).status == 'left':
        await callback_query.answer("Вы не подписались на наш канал😢", True)
    else:
        await callback_query.answer("Спасибо за подписку!❤️ Продолжайте пользоваться ботом", True)


@dp.message(CommandStart())
@security('state')
async def _start(message: Message, state: FSMContext):
    if await new_message(message): return
    if message.text.startswith('/start delete_reminder'):
        id = int(message.text.replace("/start delete_reminder_", "", 1))
        index = check_reminder(id, message.chat.id)
        if index == "NotFound":
            await message.answer(
                "Напоминание не найдено. Если возникли трудности напишите отзыв, мы во всем разберемся")
            return
        reminder = Data.reminders[index]
        if reminder.publish:
            await state.update_data(id=id, index=index)
            markup = IMarkup(inline_keyboard=[[IButton(text="Все равно удалить!",
                                                       callback_data="delete_reminder")],
                                              [IButton(text="Не удалять...",
                                                       callback_data="not_edit_reminder")]])
            await message.answer("*Внимание!*\nДанное напоминание является публичным (открытым). Если Вы удалите его, "
                                 "то оно удалится для всех!", reply_markup=markup, parse_mode=markdown)
        else:
            await db.execute("DELETE FROM reminders WHERE id=?", (id,))
            Data.reminders.pop(index)
            await message.answer("Ваше напоминание удалено!")
    elif message.text.startswith('/start edit_reminder'):
        id = int(message.text.replace("/start edit_reminder_", "", 1))
        index = check_reminder(id, message.chat.id)
        if index == "NotFound":
            await message.answer(
                "Напоминание не найдено. Если возникли трудности напишите отзыв, мы во всем разберемся")
            return
        reminder = Data.reminders[index]
        if reminder.parent != -1:
            return await message.answer("Вы не можете изменить это напоминание, только удалить")
        await state.update_data(reminder_id=id)
        if reminder.publish:
            markup = IMarkup(inline_keyboard=[[IButton(text="Все равно изменить!",
                                                       callback_data="edit_reminder")],
                                              [IButton(text="Не менять...",
                                                       callback_data="not_edit_reminder")]])
            await message.answer("*Внимание!*\nДанное напоминание является публичным (открытым). Если Вы измените его, "
                                 "то оно изменится у всех!", reply_markup=markup, parse_mode=markdown)
        else:
            markup = IMarkup(inline_keyboard=[[IButton(text="Текст", callback_data="edit_text_of_reminder")],
                                              [IButton(text="Время", callback_data="edit_time_of_reminder")]])
            await message.answer("Что вы хотите изменить в напоминании?", reply_markup=markup)
    elif message.text.startswith('/start set_publish'):
        id = int(message.text.replace("/start set_publish_", "", 1))
        index = check_reminder(id, message.chat.id)
        if index == "NotFound":
            await message.answer(
                "Напоминание не найдено. Если возникли трудности напишите отзыв, мы во всем разберемся")
            return
        reminder = Data.reminders[index]
        if reminder.frequency:
            return await message.answer("Пока что я не могу сделать публичным частое напоминание...")
        if reminder.parent != -1:
            return await message.answer("Вы не можете сделать публичное напоминание, только удалить!")
        await db.execute("UPDATE reminders SET publish=? WHERE id=?", ("1", id))
        Data.reminders[index].publish = True
        markup = IMarkup(inline_keyboard=[[IButton(text="Поделиться напоминанием",
                                                   url=f"tg://msg_url?url=t.me/{NAME}?start=new_reminder_{id}&"
                                                       f"text=Я+делюсь+с+тобой+напоминанием")]])
        await message.answer("Теперь напоминание открытое, каждый может скопировать его для себя по ссылке",
                             reply_markup=markup)
    elif message.text.startswith('/start new_reminder'):
        await state.clear()
        await (await message.answer("...Удаление клавиатурных кнопок...", reply_markup=ReplyKeyboardRemove())).delete()
        markup = IMarkup(inline_keyboard=[[IButton(text="Мои функции", callback_data="help")],
                                          [IButton(text="Настройки", callback_data="settings")]])
        await message.answer(f"Привет, {await username_acquaintance(message, 'first_name')}\n"
                             f"[tgmaksim.ru]({SITE})",
                             parse_mode=markdown, reply_markup=markup)

        id = int(message.text.replace("/start new_reminder_", "", 1))
        index = check_reminder(id, user_id="all")
        if index == "NotFound":
            await message.answer(
                "Напоминание не найдено. Если возникли трудности напишите отзыв, мы во всем разберемся")
            return
        reminder = Data.reminders[index]
        await create_new_reminder(reminder.text, reminder.str_time, message.chat.id, reminder.entities, "6", id)
        await message.answer("Открытое напоминание скопировано для Вас. Посмотреть все напоминания можно здесь /my_reminders")
    else:
        await state.clear()
        await (await message.answer("...Удаление клавиатурных кнопок...", reply_markup=ReplyKeyboardRemove())).delete()
        markup = IMarkup(inline_keyboard=[[IButton(text="Мои функции", callback_data="help")],
                                          [IButton(text="Настройки", callback_data="settings")]])
        await message.answer(f"Привет, {await username_acquaintance(message, 'first_name')}\n"
                             f"[tgmaksim.ru]({SITE})",
                             parse_mode=markdown, reply_markup=markup)


@dp.message(Command('help'))
@security()
async def _help(message: Message):
    if await new_message(message): return
    await help(message)


@dp.callback_query(F.data == "help")
@security()
async def _help_button(callback_query: CallbackQuery):
    if await new_callback_query(callback_query, "Помогите"): return
    await callback_query.message.edit_reply_markup()
    await help(callback_query.message)


async def help(message: Message):
    await message.answer("/review - оставить отзыв или предложение\n"
                         "/settings - настройки\n"
                         "/new_reminder - создать новое напоминание\n"
                         "/new_today_reminder - напоминание на сегодня\n"
                         "/new_tomorrow_reminder - напоминание на завтра\n"
                         "/new_often_reminder - частое напоминание\n"
                         "/my_reminders - мои напоминания\n"
                         f"<a href='{SITE}'>tgmaksim.ru</a>", parse_mode=html)


@dp.message(Command('settings'))
@security()
async def _settings(message: Message):
    if await new_message(message): return
    markup = IMarkup(inline_keyboard=[[IButton(
        text="Выбрать часовой пояс", callback_data="select_time_zone")]])
    await message.answer("Вы можете настроить некоторые показатели под себя 👇", reply_markup=markup)


@dp.callback_query(F.data == "settings")
@security()
async def _settings_button(callback_query: CallbackQuery):
    if await new_callback_query(callback_query, "Настройки"): return
    markup = IMarkup(inline_keyboard=[[IButton(
        text="Выбрать часовой пояс", callback_data="select_time_zone")]])
    await callback_query.message.edit_reply_markup()
    await callback_query.message.answer("Вы можете настроить некоторые показатели под себя 👇", reply_markup=markup)


@dp.callback_query(F.data == "select_time_zone")
@security('state')
async def _select_time_zone(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Выбрать часовой пояс"): return
    await callback_query.message.edit_reply_markup()
    await state.clear()
    await callback_query.message.answer("Пришлите мне ваш часовой пояс, например: Москва - 3, Омск - 6")
    await state.set_state(UserState.select_time_zone)


@dp.message(UserState.select_time_zone)
@security('state')
async def _edit_time_zone(message: Message, state: FSMContext):
    if await new_message(message): return
    try:
        time_zone = int(message.text)
    except ValueError:
        await message.reply("Это не число!")
    else:
        await set_time_zone(message.chat.id, time_zone)
        Data.settings[message.chat.id].time_zone = str(time_zone)
        await state.clear()
        await message.answer(f"Вы успешно изменили часовой пояс на {'+' if time_zone > 0 else ''}{time_zone}")


@dp.message(Command('cancel'))
@security('state')
async def _cancel(message: Message, state: FSMContext):
    if await new_message(message): return
    await state.clear()
    await message.answer("Действие отменено", reply_markup=ReplyKeyboardRemove())


@dp.message(Command('my_reminders'))
@security()
async def _my_reminders(message: Message):
    if await new_message(message): return
    user_reminders = []
    time_zone = Data.settings[message.chat.id].time_zone
    for reminder in Data.reminders:
        if reminder.chat_id == message.chat.id:
            user_reminders.append(reminder.my_reminders(int(time_zone)))
    if not user_reminders:
        return await message.answer("У Вас нет активных напоминаний")
    text = "\n\n".join(map(lambda x: x, user_reminders))
    await message.answer(text=text, parse_mode=html, disable_web_page_preview=True)


@dp.callback_query(F.data == "edit_reminder")
@security()
async def _confirm_edit_reminder(callback_query: CallbackQuery):
    if await new_callback_query(callback_query, "Подтверждение изменения"): return
    await callback_query.message.edit_text(callback_query.message.text + "\n\n✅Хорошо!")
    markup = IMarkup(inline_keyboard=[[IButton(text="Текст", callback_data="edit_text_of_reminder")],
                                      [IButton(text="Время", callback_data="edit_time_of_reminder")]])
    await callback_query.message.answer("Что вы хотите изменить в напоминании?", reply_markup=markup)


@dp.callback_query(F.data == "not_edit_reminder")
@security('state')
async def _not_edit_reminder(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Отмена изменения"): return
    await callback_query.message.edit_text(callback_query.message.text + "\n\n❌Хорошо!")
    await state.clear()


@dp.callback_query(F.data == "delete_reminder")
@security('state')
async def _confirm_delete_reminder(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Подтверждение удаления"): return
    await callback_query.message.edit_text(callback_query.message.text + "\n\n✅Хорошо!")
    data = await state.get_data()
    id = data['id']
    index = data['index']
    this_reminder = Data.reminders[index]
    reminders_for_delete = []
    for i, reminder in enumerate(Data.reminders):
        if reminder.parent == this_reminder.id:
            await db.execute("DELETE FROM reminders WHERE id=?", (reminder.id,))
            reminders_for_delete.append(i)
    for i in reminders_for_delete:
        Data.reminders.pop(i)
    await db.execute("DELETE FROM reminders WHERE id=?", (id,))
    Data.reminders.pop(index)
    await callback_query.message.answer("Публичное напоминание удалено у Вас и у всех, кто его скопировал!")
    await state.clear()


@dp.callback_query(F.data == "not_delete_reminder")
@security('state')
async def _not_delete_reminder(callback_query: CallbackQuery, state: FSMContext):
    if new_callback_query(callback_query, "Отмена удаления"): return
    await callback_query.message.edit_text(callback_query.message.text + "\n\n❌Хорошо!")
    await state.clear()


@dp.callback_query(F.data == "edit_text_of_reminder")
@security('state')
async def _edit_text_of_reminder(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Изменить текст"): return
    await state.set_state(UserState.edit_reminder)
    await state.update_data(edit_reminder="text")
    await callback_query.message.edit_text(callback_query.message.text + "\nТекст", reply_markup=None)
    await callback_query.message.answer("Отправьте мне измененный текст напоминания")


@dp.callback_query(F.data == "edit_time_of_reminder")
@security('state')
async def _edit_time_of_reminder(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Изменить время"): return
    await state.set_state(UserState.edit_reminder)
    await state.update_data(edit_reminder="time")
    await callback_query.message.edit_text(callback_query.message.text + "\nВремя", reply_markup=None)
    time_zone = Data.settings[callback_query.message.chat.id].time_zone
    markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Выбрать дату и время...", web_app=WebAppInfo(
        url=Data.url_select_datetime + time_zone))]])
    await callback_query.message.answer("Отправьте мне новое время напоминания или нажмите ниже", reply_markup=markup)


@dp.message(UserState.edit_reminder)
@security('state')
async def _edit_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    edit = (await state.get_data())['edit_reminder']
    reminder_id = (await state.get_data())['reminder_id']
    index = check_reminder(reminder_id, message.chat.id)
    if index == "NotFound":
        await state.clear()
        return await message.answer("Напоминание не найдено!")
    if edit == "text":
        if message.content_type != "text":
            return await message.answer("Пока что напоминалка работает только с текстом!")
        text = message.text
        entities = message.entities
        await state.clear()
        await edit_text_reminder(reminder_id, text, entities)
        this_reminder = Data.reminders[index]
        if this_reminder.publish:
            for reminder in Data.reminders:
                if reminder.parent == this_reminder.id:
                    await edit_text_reminder(reminder.id, text, entities)
            await message.answer("Текст напоминания изменен для вас и всех, кто скопировал напоминание ранее!")
        else:
            await message.answer("Текст напоминания изменен!")
    else:
        if message.content_type not in ("text", "web_app_data"):
            return await message.answer("Некорректно!")
        str_time = message.text if message.text else message.web_app_data.data
        time_reminder = check_str_time(str_time)
        if not time_reminder:
            return await message.answer("Некорректное время...")
        time_zone = Data.settings[message.chat.id].time_zone
        time_reminder += timedelta(hours=int(time_zone) - 6)
        if time_reminder <= time_now() and not Data.reminders[check_reminder(reminder_id, "all")].frequency:
            return await message.answer("Это время уже прошло...")
        await state.clear()
        await edit_time_reminder(reminder_id, str_time, time_reminder)
        this_reminder = Data.reminders[index]
        if this_reminder.publish:
            for reminder in Data.reminders:
                if reminder.parent == this_reminder.id:
                    await edit_time_reminder(reminder.id, str_time, time_reminder)
            await message.answer("Время напоминания изменено для Вас и всех, кто его скопировал!",
                                 reply_markup=ReplyKeyboardRemove())
        else:
            await message.answer("Время напоминания изменено!", reply_markup=ReplyKeyboardRemove())


@dp.message(Command('new_tomorrow_reminder', 'new_today_reminder', 'new_reminder'))
@security('state')
async def _create_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    await state.set_state(UserState.create_new_reminder)
    await state.update_data(day=message.text.split(" ", 1)[0].replace("/new_", "").replace("reminder", "").replace("_", ""))
    await message.answer("Напишите *текст* Вашего напоминания\nЧтобы отменить - /cancel", parse_mode=markdown)


@dp.message(Command('new_often_reminder'))
@security('state')
async def _create_often_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    await state.set_state(UserState.create_new_often_reminder)
    await message.answer("Напишите *текст* напоминания\nЧтобы отменить - /cancel", parse_mode=markdown)


@dp.message(UserState.create_new_reminder)
@security('state')
async def _text_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    if not message.text:
        return await message.answer("Пока что напоминалка работает только с текстом!")
    day = (await state.get_data())['day']
    await state.update_data(text=message.text, entities=message.entities)
    time_zone = Data.settings[message.chat.id].time_zone
    markup = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="Выбрать дату и время...",
            web_app=WebAppInfo(url=Data.url_select_datetime + time_zone if not day else Data.url_select_time + time_zone))]])
    await message.answer(f"Отправьте *время* напоминания или нажмите ниже\n"
                         "Чтобы отменить - /cancel", parse_mode=markdown, reply_markup=markup)
    await state.set_state(UserState.text_new_reminder)


@dp.message(UserState.create_new_often_reminder)
@security('state')
async def _text_often_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    if not message.text:
        return await message.answer("Пока что напоминалка работает только с текстом!")
    await state.update_data(text=message.text, entities=message.entities)
    time_zone = Data.settings[message.chat.id].time_zone
    markup = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Выбрать дату и время...", web_app=WebAppInfo(url=Data.url_select_datetime + time_zone))]])
    await message.answer("Отправьте *время* напоминания или нажмите ниже\n"
                         "Чтобы отменить - /cancel", parse_mode=markdown, reply_markup=markup)
    await state.set_state(UserState.text_new_often_reminder)


@dp.message(UserState.text_new_reminder)
@security('state')
async def _time_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    if message.content_type not in ("text", "web_app_data"):
        return await message.answer("Некорректно!")
    time = message.text if message.text else message.web_app_data.data
    data = await state.get_data()
    text = data['text']
    entities = data['entities'] or []
    time_zone = Data.settings[message.chat.id].time_zone
    now = time_now()
    match data['day']:
        case "":
            answer = await create_new_reminder(text, time, message.chat.id, entities, time_zone, -1)
        case 'today':
            answer = await create_new_reminder(text, f"{now.year}/{now.month}/{now.day} {time}",
                                               message.chat.id, entities, time_zone, -1)
        case 'tomorrow':
            answer = await create_new_reminder(text, f"{now.year}/{now.month}/{now.day + 1} {time}",
                                               message.chat.id, entities, time_zone, -1)
        case _:
            return
    if answer == -1:
        await message.answer("Это время уже прошло...")
    elif answer is True:
        await message.answer("Ваше напоминание успешно создано", reply_markup=ReplyKeyboardRemove())
        await state.clear()
    else:
        await message.answer("Вы неправильно ввели дату!")


@dp.message(UserState.text_new_often_reminder)
@security('state')
async def _time_often_reminder(message: Message, state: FSMContext):
    if await new_message(message): return
    if message.content_type not in ("text", "web_app_data"):
        return await message.answer("Некорректно!")
    text = message.text if message.text else message.web_app_data.data
    time = check_str_time(text)
    if time:
        await bot.delete_message(
            message.chat.id,
            (await message.answer("Время успешно обработано...", reply_markup=ReplyKeyboardRemove())).message_id)
        await state.update_data(time=text)
        markup = IMarkup(inline_keyboard=[
            [IButton(text=text, callback_data=data)] for text, data in Data.frequency_reminders])
        await message.answer("Выберите частоту напоминания:", reply_markup=markup)
        await state.set_state(UserState.time_new_often_reminder)
    else:
        await message.answer("Вы неправильно ввели время")


@dp.callback_query(UserState.time_new_often_reminder, F.data.in_(list(Data.text_frequency)))
@security('state')
async def _frequency_reminder(callback_query: CallbackQuery, state: FSMContext):
    if await new_callback_query(callback_query, "Частое напоминание"): return
    data = await state.get_data()
    text = data['text']
    time = data['time']
    entities = data['entities'] or []
    frequency = callback_query.data
    time_zone = Data.settings[callback_query.from_user.id].time_zone
    await create_new_often_reminder(text, time, callback_query.message.chat.id, frequency, entities, time_zone)
    await state.clear()
    await callback_query.message.answer("Ваше напоминание успешно создано")
    await callback_query.message.edit_text(f"Выберите частоту напоминания:\n\n*{Data.text_frequency[frequency]}*",
                                           parse_mode=markdown)


@dp.callback_query(F.data.in_([f"replay_{i}" for i in Data.text_replay]))
@security()
async def _replay_reminder(callback_query: CallbackQuery):
    if await new_callback_query(callback_query, "Повторить напоминание"): return
    replay = callback_query.data.replace("replay_", "", 1)
    add = {"day": timedelta(days=1), "week": timedelta(weeks=1),
           "5minutes": timedelta(minutes=5), "hour": timedelta(hours=1)}
    time = omsk_time(callback_query.message.date) + add[replay]
    text = callback_query.message.text
    entities = callback_query.message.entities or []
    time_zone = Data.settings[callback_query.from_user.id].time_zone
    await create_new_reminder(text, time.strftime('%Y/%m/%d %H.%M'), callback_query.message.chat.id, entities, time_zone, -1)
    await callback_query.message.delete_reply_markup()
    await callback_query.message.reply(f"Напоминание повторено {Data.text_replay[replay]}")


@dp.callback_query()
@security()
async def _other_callback_query(callback_query: CallbackQuery):
    await new_callback_query(callback_query, "Неизвестно...")


@dp.message()
@security()
async def _other_messages(message: Message):
    await new_message(message)


def check_str_time(str_time: str, *, two_objects: bool = False):
    _time = re.fullmatch(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2}) (?P<hour>\d{1,2})[.:](?P<minute>\d{1,2})",
                          str_time)
    if not _time:
        return
    _date_time = datetime(year=int(_time.group("year")), month=int(_time.group("month")), day=int(_time.group("day")),
                          hour=int(_time.group("hour")), minute=int(_time.group("minute")))
    return _date_time if not two_objects else (_time, _date_time)


async def create_new_reminder(text: str, str_time: str, chat_id: int, entities: list[MessageEntity], time_zone: str, parent: int):
    _time = check_str_time(str_time)
    if _time:
        _time = _time + timedelta(hours=int(time_zone) - 6)
        if _time <= time_now():
            return -1
        id = int((await db.execute("SELECT value FROM system_data WHERE key=?", ("max_id_reminder",)))[0][0]) + 1
        await db.execute("UPDATE system_data SET value=? WHERE key=?", (str(id), "max_id_reminder"))
        Data.reminders.append(Reminder(id, chat_id, text, _time, str_time, "", entities, False, parent))
        await db.execute("INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (id, chat_id, text, str_time, "", entities_format_list(entities), "0", parent))
        return True
    else:
        return False


async def create_new_often_reminder(text: str, str_time: str, chat_id: int, frequency: str, entities: list[MessageEntity], time_zone: str):
    _time = check_str_time(str_time)
    _time = _time + timedelta(hours=int(time_zone) - 6)
    id = int((await db.execute("SELECT value FROM system_data WHERE key=?", ("max_id_reminder",)))[0][0]) + 1
    await db.execute("UPDATE system_data SET value=? WHERE key=?", (str(id), "max_id_reminder"))
    Data.reminders.append(Reminder(id, chat_id, text, _time, str_time, frequency, entities, False, -1))
    await db.execute("INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (id, chat_id, text, str_time, frequency, entities_format_list(entities), "0", -1))


async def edit_text_reminder(reminder_id: int, text: str, entities: list[MessageEntity]):
    index = check_reminder(reminder_id, "all")
    Data.reminders[index].text = text
    Data.reminders[index].entities = entities
    await db.execute("UPDATE reminders SET text=? WHERE id=?", (text, reminder_id))
    await db.execute("UPDATE reminders SET entities=? WHERE id=?", (entities_format_list(entities), reminder_id))


async def edit_time_reminder(reminder_id: int, str_time: str, time_reminder: datetime):
    index = check_reminder(reminder_id, "all")
    Data.reminders[index].str_time = str_time
    Data.reminders[index].time = time_reminder
    await db.execute("UPDATE reminders SET str_time=? WHERE id=?", (str_time, reminder_id))


def entities_format_str(entities: str) -> list[MessageEntity]:
    default_entity = MessageEntity(type="bold", offset=0, length=0)
    result = [default_entity.model_copy(update=entity) for entity in json.JSONDecoder().decode(entities)]
    return result


def entities_format_list(entities: list[MessageEntity]) -> str:
    result = [entity.model_dump() for entity in entities or []]
    return json.JSONEncoder().encode(result)


def check_reminder(reminder_id: int, user_id: int | Literal["all"]) -> int | Literal["NotFound"]:
    for i, reminder in enumerate(Data.reminders):
        if reminder.id == reminder_id:
            if reminder.chat_id == user_id or user_id == "all":
                return i
            else:
                return "NotFound"
    else:
        return "NotFound"


async def wait_reminders():
    while True:
        delete_reminders = []
        for i, reminder in enumerate(Data.reminders):
            if reminder():
                await send_reminder(reminder)
                not reminder.frequency and delete_reminders.append(i)
        for i in delete_reminders:
            Data.reminders.pop(i)
        await asyncio.sleep(60)


async def send_reminder(reminder: Reminder):
    markup = IMarkup(inline_keyboard=[[IButton(
        text=f"Повторить {Data.text_replay[i]}", callback_data=f"replay_{i}")] for i in Data.text_replay])
    try:
        await bot.send_sticker(reminder.chat_id,
                               'CAACAgIAAxkBAAIKU2VEcBh507fXYGMqRZWvNPKFWLslAALvQgACnisgSr_4ZR4YZGHQMwQ')
        await bot.send_message(reminder.chat_id, reminder.text, entities=reminder.entities, reply_markup=markup if not reminder.frequency else None)
    except Exception as e:
        await bot.send_message(OWNER, f"Произошла ошибка {e.__class__.__name__} при отправке напоминания: {e}")
    else:
        if reminder.chat_id != OWNER:
            await bot.send_message(OWNER, f"Сработала напоминание у {reminder.chat_id}\n{reminder.text}")
    finally:
        if not reminder.frequency:
            await db.execute("DELETE FROM reminders WHERE id=?", (reminder.id,))


async def new_user(message: Message):
    if not await db.execute("SELECT id FROM users WHERE id=?", (str(message.chat.id),)):
        await db.execute("INSERT INTO users VALUES(?, ?)", (message.chat.id, ""))
        Data.users.add(message.chat.id)
    await db.execute("UPDATE users SET last_message=? WHERE id=?", (str(omsk_time(message.date)), message.chat.id))


async def username_acquaintance(message: Message, default: Literal[None, 'first_name'] = 'None'):
    id = message.chat.id
    user = await db.execute("SELECT name FROM acquaintances WHERE id=?", (id,))
    if user:
        return user[0][0]
    return message.from_user.first_name if default == 'first_name' else None


async def developer_command(message: Message) -> bool:
    if message.chat.id == OWNER:
        await new_message(message, False)
        await message.answer("*Команда разработчика активирована!*", parse_mode=markdown)
    else:
        await new_message(message)
        await message.answer("*Команда разработчика НЕ была активирована*", parse_mode=markdown)

    return message.chat.id != OWNER


async def subscribe_to_channel(message: Message):
    if (await bot.get_chat_member(channel, message.from_user.id)).status == 'left' and not message.text.startswith('/start'):
        markup = IMarkup(
            inline_keyboard=[[IButton(text="Подписаться на канал", url=subscribe)],
                             [IButton(text="Подписался", callback_data="subscribe")]])
        await message.answer("Бот работает только с подписчиками моего канала. "
                             "Подпишитесь и получите полный доступ к боту", reply_markup=markup)
        return False
    return True


async def new_message(message: Message, forward: bool = True) -> bool:
    if message.content_type == "text":
        content = message.text
    elif message.content_type == "web_app_data":
        content = message.web_app_data.data
    else:
        content = f"<{message.content_type}>"
    id = str(message.chat.id)
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    date = str(omsk_time(message.date))
    acquaintance = await username_acquaintance(message)
    acquaintance = f"<b>Знакомый: {acquaintance}</b>\n" if acquaintance else ""

    await db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                     (id, username, first_name, last_name, content, date))

    if message.chat.id == OWNER:
        return False

    if message.content_type not in ("text", "web_app_data"):  # Если сообщение не является текстом или ответом mini app
        await bot.send_message(
            OWNER,
            text=f"ID: {id}\n"
                 f"{acquaintance}" +
                 (f"USERNAME: @{username}\n" if username else "") +
                 f"Имя: {first_name}\n" +
                 (f"Фамилия: {last_name}\n" if last_name else "") +
                 f"Время: {date}",
            parse_mode=html)
        await message.forward(OWNER)
    elif forward or (message.entities and message.entities[0].type != 'bot_command'):  # Если сообщение содержит форматирование или необходимо переслать сообщение
        if message.entities and message.entities[0].type != 'bot_command':
            await bot.send_message(
                OWNER,
                text=f"ID: {id}\n"
                     f"{acquaintance}" +
                     (f"USERNAME: @{username}\n" if username else "") +
                     f"Имя: {first_name}\n" +
                     (f"Фамилия: {last_name}\n" if last_name else "") +
                     f"Время: {date}",
                parse_mode=html)
            await message.forward(OWNER)
        else:  # Если сообщение не содержит форматирование и его не нужно пересылать
            try:
                await bot.send_message(
                    OWNER,
                    text=f"ID: {id}\n"
                         f"{acquaintance}" +
                         (f"USERNAME: @{username}\n" if username else "") +
                         f"Имя: {first_name}\n" +
                         (f"Фамилия: {last_name}\n" if last_name else "") +
                         (f"<code>{content}</code>\n"
                          if not content.startswith("/") or len(content.split()) > 1 else f"{content}\n") +
                         f"Время: {date}",
                    parse_mode=html)
            except:
                await bot.send_message(
                    OWNER,
                    text=f"ID: {id}\n"
                         f"{acquaintance}" +
                         (f"USERNAME: @{username}\n" if username else "") +
                         f"Имя: {first_name}\n" +
                         (f"Фамилия: {last_name}\n" if last_name else "") +
                         f"<code>{content}</code>\n"
                         f"Время: {date}",
                    parse_mode=html)
                await message.forward(OWNER)

    if message.chat.id not in Data.users:
        await message.forward(OWNER)
    if not Data.settings.get(message.chat.id):
        Data.settings[message.chat.id] = Settings.default(message.chat.id)
        await set_time_zone(message.chat.id, 6)
        markup = IMarkup(inline_keyboard=[[IButton(text="Выбрать часовой пояс", callback_data="select_time_zone")]])
        await message.answer("*У Вас не выбран часовой пояс!* Выберите его сейчас👇 или оставьте часовой пояс по "
                             "умолчанию: UTC*+06:00* (Омск, Россия)\nВы всегда можете изменить его в настройках "
                             "/settings", parse_mode=markdown, reply_markup=markup)
    await new_user(message)

    return not await subscribe_to_channel(message)


async def new_callback_query(callback_query: CallbackQuery, comment: str) -> bool:
    message = callback_query.message
    id = str(message.chat.id)
    username = callback_query.from_user.username
    first_name = callback_query.from_user.first_name
    last_name = callback_query.from_user.last_name
    callback_data = callback_query.data
    date = str(omsk_time(message.date))
    acquaintance = await username_acquaintance(message)
    acquaintance = f"<b>Знакомый: {acquaintance}</b>\n" if acquaintance else ""
    comment = f"Комментарий: {comment}\n" if comment else ""

    await db.execute("INSERT INTO callbacks_query VALUES (?, ?, ?, ?, ?, ?)",
                     (id, username, first_name, last_name, callback_data, date))

    if callback_query.from_user.id != OWNER:
        await bot.send_message(
            OWNER,
            text=f"ID: {id}\n"
                 f"{acquaintance}" +
                 (f"USERNAME: @{username}\n" if username else "") +
                 f"Имя: {first_name}\n" +
                 (f"Фамилия: {last_name}\n" if last_name else "") +
                 f"CALLBACK_DATA: {callback_data}\n"
                 f"{comment}"
                 f"Время: {date}",
            parse_mode=html)

    return False


async def start_bot():
    await db.execute("CREATE TABLE IF NOT EXISTS messages (id TEXT, username TEXT, first_name TEXT, last_name TEXT, "
                     "message_text TEXT, datetime TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS callbacks_query (id TEXT, username TEXT, first_name TEXT, "
                     "last_name TEXT, callback_data TEXT, datetime TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS system_data (key TEXT, value TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS acquaintances (id TEXT, username TEXT, first_name TEXT, "
                     "last_name TEXT, name TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS users (id TEXT, last_message TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER, chat_id INTEGER, text TEXT, "
                     "str_time TEXT, frequency TEXT, entities TEXT, publish TEXT, parent INTEGER)")
    await db.execute("CREATE TABLE IF NOT EXISTS settings (id TEXT, time_zone TEXT)")
    if not await db.execute("SELECT value FROM system_data WHERE key=?", ("pause",)):
        await db.execute("INSERT INTO system_data VALUES(?, ?)", ("pause", "False"))
    if not await db.execute("SELECT value FROM system_data WHERE key=?", ("version",)):
        await db.execute("INSERT INTO system_data VALUES(?, ?)", ("version", "0.0"))
    if not await db.execute("SELECT value FROM system_data WHERE key=?", ("max_id_reminder",)):
        await db.execute("INSERT INTO system_data VALUES(?, ?)", ("max_id_reminder", "-1"))

    for id, chat_id, text, str_time, frequency, entities, publish, parent in await db.execute("SELECT * FROM reminders"):
        time = check_str_time(str_time)
        if not frequency and time <= time_now():
            await db.execute("DELETE FROM reminders WHERE id=?", (id,))
            continue
        Data.reminders.append(Reminder(id, chat_id, text, time, str_time, frequency, entities_format_str(entities), publish == "1", parent))

    Data.users = await get_users()
    Data.settings = Settings.load_settings(await get_settings())

    await bot.send_message(OWNER, f"*Бот запущен!🚀*", parse_mode=markdown)
    print("Запуск бота")
    await dp.start_polling(bot)


def check_argv():
    program_variant = sys.argv[1]
    if program_variant not in ("release", "debug"):
        raise TypeError("Выберите вариант запуска программы: release или debug")


if __name__ == '__main__':
    check_argv()
    main_loop = asyncio.get_event_loop()
    main_loop.create_task(start_bot())
    main_loop.create_task(wait_reminders())
    main_loop.run_forever()
