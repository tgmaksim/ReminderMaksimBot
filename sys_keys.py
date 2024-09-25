import sys
import os
from dotenv import load_dotenv


dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)


RELEASE_TOKEN = os.environ['ReminderMaksimBot']  # Напоминалка
DEBUG_TOKEN = os.environ['TestMaksimBot']  # Тест бот
TOKEN = RELEASE_TOKEN if sys.argv[1] == "release" else DEBUG_TOKEN

release_resources_path = lambda path, name: f"/home/c87813/tgmaksim.ru/TelegramBots/{name}/resources/{path}"  # netangels
debug_resources_path = lambda path, name: f"resources/{path}"  # Локально
resources_path = release_resources_path if sys.argv[1] == "release" else debug_resources_path

RELEASE_NAME = "ReminderMaksimBot"  # Напоминалка
DEBUG_NAME = "TestMaksimBot"  # Тест бот
NAME = RELEASE_NAME if sys.argv[1] == "release" else DEBUG_NAME

api_key = os.environ['ApiKey']
process_id = os.environ['ProcessIdReminderMaksimBot']
