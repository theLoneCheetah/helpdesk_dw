"""
Заполнение измерений ХД helpdesk_dw (PyMySQL):
- DimDate
- DimOperator
- DimCustomer
"""

import random
from datetime import date, timedelta
import pymysql
from faker import Faker
from db_config import DB_CONFIG

fake = Faker("ru_RU")   # генератор псевдослучайных данных для заполнения БД
random.seed(42)   # воспроизводимость

# Подключение к БД
def get_connection():
    return pymysql.connect(
        **DB_CONFIG,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )

# Функция генерации календаря в рамках дат
def build_dim_date(start: date, end: date) -> list[tuple]:
    rows = []
    d = start
    month_names_ru = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]
    day_names_ru = [
        "Понедельник", "Вторник", "Среда", "Четверг",
        "Пятница", "Суббота", "Воскресенье",
    ]

    # Проход по всем дням
    while d <= end:
        date_key = int(d.strftime("%Y%m%d"))
        iso = d.isocalendar()   # (year, week, weekday)
        rows.append((
            date_key,
            d,
            d.year,
            (d.month - 1) // 3 + 1,   # квартал
            d.month,
            month_names_ru[d.month - 1],
            d.day,
            d.isoweekday(),   # 1..7
            day_names_ru[d.isoweekday() - 1],
            iso[1],   # номер недели в году
            1 if d.isoweekday() >= 6 else 0,   # выходной/нет
        ))
        d += timedelta(days=1)
    return rows

# Заполнение DimDate датами за 2024-начало 2026 года
def load_dim_date(cursor):
    print("Заполняем DimDate...")
    rows = build_dim_date(date(2024, 1, 1), date(2026, 1, 5))   # создаём список дат
    cursor.executemany(
        """
        INSERT INTO DimDate
        (DateKey, FullDate, Year, Quarter, Month, MonthName,
         DayOfMonth, DayOfWeek, DayName, WeekOfYear, IsWeekend)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )
    print(f" -> вставлено {len(rows)} строк")

# Таблица DimOperator
OPERATORS = [
    ("ОП-01", "Иванова Анна Сергеевна",      3, "2019-03-12"),
    ("ОП-02", "Петров Дмитрий Олегович",     3, "2018-09-01"),
    ("ОП-03", "Смирнова Елена Игоревна",     2, "2020-06-15"),
    ("ОП-04", "Кузнецов Артём Викторович",   2, "2021-02-01"),
    ("ОП-05", "Соколова Мария Павловна",     2, "2021-11-22"),
    ("ОП-06", "Новиков Игорь Андреевич",     1, "2023-04-10"),
    ("ОП-07", "Морозова Ольга Дмитриевна",   1, "2023-08-05"),
    ("ОП-08", "Волков Сергей Николаевич",    1, "2024-01-15"),
]

# Заполнение DimOperator
def load_dim_operator(cursor):
    print("Заполняем DimOperator...")
    cursor.executemany(
        """
        INSERT INTO DimOperator (OperatorID, Name, Category, HireDate)
        VALUES (%s, %s, %s, %s)
        """,
        OPERATORS,
    )
    print(f" -> вставлено {len(OPERATORS)} строк")

# Города в ЛО и тарифные планы
CITIES = [
    ("Санкт-Петербург", False),
    ("Колпино",         False),
    ("Пушкин",          False),
    ("Гатчина",         False),
    ("Всеволожск",      False),
    
]
VILLAGES = [
    ("Токсово",         True),
    ("Сертолово",       True),
    ("Бугры",           True),
    ("Мурино",          True),
    ("Новое Девяткино", True),
]
TARIFFS = [
    "Базовый 100 Мбит/с",
    "Стандарт 300 Мбит/с",
    "Оптимальный 500 Мбит/с",
    "Премиум 1 Гбит/с",
    "Социальный 50 Мбит/с",
]

# Генерация DimCustomer — 100 клиентов, ~15% в деревне
def build_customers(n: int = 100) -> list[tuple]:
    rows = []
    for i in range(1, n + 1):
        customer_id = f"Д-{1000 + i}"
        name = fake.name() 
        city, is_village = random.choices([CITIES, VILLAGES], weights=[0.85, 0.15])[0][0]
        street = fake.street_name()
        house = str(random.randint(1, 120))
        building = str(random.randint(1, 4)) if random.random() < 0.2 else None
        apartment = str(random.randint(1, 300))
        tariff = random.choice(TARIFFS)
        rows.append((
            customer_id, name, city, street, house,
            building, apartment, int(is_village), tariff,
        ))
    return rows

# Заполняем DimCustomer
def load_dim_customer(cursor):
    print("Заполняем DimCustomer…")
    rows = build_customers(100)
    cursor.executemany(
        """
        INSERT INTO DimCustomer
        (CustomerID, Name, City, Street, House,
         Building, Apartment, IsVillage, TariffPlan)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )
    print(f" -> вставлено {len(rows)} строк")

# Main
def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        load_dim_date(cursor)
        load_dim_operator(cursor)
        load_dim_customer(cursor)
        conn.commit()
        print("\nВсё успешно загружено.")
    # Безопасный откат транзакций при исключениях
    except pymysql.MySQLError as e:
        conn.rollback()
        print(f"\nОшибка MySQL: {e}")
        raise
    except Exception as e:
        conn.rollback()
        print(f"\nОшибка: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()