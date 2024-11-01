import sys
import os
from dotenv import load_dotenv


release = sys.argv[1] == "release"

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

RELEASE_TOKEN = os.environ['ReminderMaksimBot']  # Напоминалка
DEBUG_TOKEN = os.environ['TestMaksimBot']  # Тест бот
TOKEN = RELEASE_TOKEN if release else DEBUG_TOKEN

release_resources_path = lambda path: f"/home/c87813/reminder.tgmaksim.ru/TelegramBot/resources/{path}"  # netangels
debug_resources_path = lambda path: f"resources/{path}"  # Локально
resources_path = release_resources_path if release else debug_resources_path

RELEASE_NAME = "ReminderMaksimBot"  # Напоминалка
DEBUG_NAME = "TestMaksimBot"  # Тест бот
NAME = RELEASE_NAME if release else DEBUG_NAME

api_key = os.environ['ApiKey']
db = {"host": os.environ["DBHOST"], "user": os.environ["DBUSER"], "password": os.environ['DBPASS'],
      "unix_socket": "/var/run/mysqld/mysqld.sock"} if release else None
