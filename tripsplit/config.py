from dotenv import load_dotenv
import os

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_MEMBERS_DB_ID = os.environ["NOTION_MEMBERS_DB_ID"]
NOTION_EXPENSES_DB_ID = os.environ["NOTION_EXPENSES_DB_ID"]
