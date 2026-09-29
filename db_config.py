import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": os.getenv("DB_PASSWORD"),
    "database": "helpdesk_dw",
    "charset": "utf8mb4",
}