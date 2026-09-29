"""
Генерация и загрузка FactTickets для ХД helpdesk_dw.

Модель:
- Цикл по календарю 2024-01-01 … 2025-12-31 (731 день).
- Каждый день — 4 оператора, выбираются случайно из 8.
- Объём звонков за день зависит от дня недели.
- Нагрузка между операторами распределяется неравномерно.
- Каждый звонок: тип проблемы → P(resolved) → длительность → группа назначения.
- Эффект спешки: при нагрузке выше средней — звонки короче, но и процент решённых ниже.
- Опыт оператора (категория 1–3) — главный фактор и длительности, и решаемости.
- "Неработающее оборудование по адресу" всегда Resolved=TRUE, группа "Внутренняя заявка".
"""

import random
from datetime import date, datetime, timedelta
import pymysql
from db_config import DB_CONFIG

random.seed(42)

# Параметры генерации
START_DATE = date(2024, 1, 1)
END_DATE   = date(2025, 12, 31)

# Распределение звонков по часам суток (пики утром и вечером)
HOUR_WEIGHTS = [
    1.0, 0.5, 0.3, 0.2, 0.2, 0.3,   # 0–5
    0.7, 1.5, 2.5, 3.5, 4.0, 4.0,   # 6–11
    2.5, 2.5, 3.0, 3.0, 3.0, 3.5,   # 12–17
    4.0, 4.5, 4.5, 3.5, 2.0, 1.3,   # 18–23
]

# Тип проблемы (имя, вес, базовая P(resolved))
PROBLEMS = [
    ("Проверка интернета",                    0.25, 0.85),
    ("Настройка роутера",                     0.15, 0.75),
    ("Низкая скорость",                       0.15, 0.55),
    ("Вопросы IPTV",                          0.10, 0.75),
    ("Неработающее оборудование по адресу",   0.10, 1.00),   # закрывается общей группой в OLTP
    ("Повреждение кабеля",                    0.10, 0.25),
    ("Вопросы по сетевой настройке",          0.10, 0.65),
    ("Дополнительные платные услуги мастера", 0.05, 0.00),
]

# Группы назначения (имя, доля для города, доля для деревни)
GROUPS = [
    ("Офисные инженеры",          0.30, 0.30),
    ("Мастер",                    0.50, 0.00),
    ("Восстановительная бригада", 0.20, 0.00),
    ("Мастер в деревне",          0.00, 0.70),
]

# Категория оператора -> коэффициент опыта (1.0 = опытный)
EXPERIENCE = {1: 0.4, 2: 0.7, 3: 1.0}

# Коэффициенты эффекта спешки
K_DURATION        = 0.20   # длительность падает на 20% при +100% нагрузки
K_RESOLVED_PEN    = 0.08   # P(resolved) падает на 0.08 при +100% нагрузки
K_RESOLVED_BONUS  = 0.03   # P(resolved) растёт на 0.03 при −100% нагрузки

# Доля тикетов в поле, оставшихся открытыми
OPEN_TICKET_PROB = 0.05


# Подключение к БД
def get_connection():
    return pymysql.connect(
        **DB_CONFIG,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )

# Чтение измерений
def load_dict(cursor, table, key_col, name_col):
    cursor.execute(f"SELECT {key_col}, {name_col} FROM {table}")
    return {row[name_col]: row[key_col] for row in cursor.fetchall()}

# Чтение таблицы операторов
def load_operators(cursor):
    cursor.execute("SELECT OperatorKey, OperatorID, Name, Category FROM DimOperator")
    return cursor.fetchall()

# Чтение таблицы клиентов
def load_customers(cursor):
    cursor.execute("SELECT CustomerKey, CustomerID, IsVillage FROM DimCustomer")
    return cursor.fetchall()

# Модель одного звонка
def compute_duration(exp, resolved, is_internal, load_norm, op_factor):
    """
    Длительность звонка, сек:
      base = 200 + (1 - exp) * 150               (200…350 сек в зависимости от опыта)
      + 60…120 сек, если решили на линии         (объясняем клиенту)
      − 30…60 сек, если передали в группу        (быстро оформили заявку)
      × (1 − load_norm * K_DURATION)             (эффект спешки)
      + N(0, 45)                                 (шум)
      clip: [60; 900]
    """
    base = (200 + (1 - exp) * 150) * op_factor

    if is_internal:   # для внутренних надбавки нет
        pass
    elif resolved:
        base += random.uniform(60, 120)
    else:
        base -= random.uniform(30, 60)

    if load_norm > 0:   # при повышенной нагрузке
        base *= (1 - load_norm * K_DURATION)
    else:
        base *= (1 + abs(load_norm) * K_DURATION * 0.5)   # бонус слабее штрафа

    duration = base + random.gauss(0, 45)
    return max(60, min(900, int(duration)))

def compute_p_resolved(base_p, category, load_norm):
    """
    P(решено на линии):
      base_p
      + 0.10 для cat 3 / − 0.10 для cat 1
      − load_norm * K_RESOLVED_PEN (если нагрузка выше средней)
      + |load_norm| * K_RESOLVED_BONUS (если ниже средней)
      + N(0, 0.03) шум
      clip: [0.02; 0.98]
    """
    p = base_p
    if category == 3:
        p += 0.10
    elif category == 1:
        p -= 0.10

    if load_norm > 0:
        p -= load_norm * K_RESOLVED_PEN
    else:
        p += abs(load_norm) * K_RESOLVED_BONUS

    p += random.gauss(0, 0.03)
    return max(0.02, min(0.98, p))

def pick_assignment_group(customer):
    """Взвешенный выбор группы с учётом типа клиента."""
    weights = [g[2] if customer["IsVillage"] else g[1] for g in GROUPS]
    names = [g[0] for g in GROUPS]
    return random.choices(names, weights=weights, k=1)[0]

def pick_scheduled_date(call_date, group_name):
    """Дата выезда для групп с выездом. Офисные инженеры — None."""
    if group_name == "Офисные инженеры":
        return None
    r = random.random()
    if r < 0.10:
        offset = 0                      # 10% - срочный выезд сегодня
    elif r < 0.85:
        offset = 1                      # 75% - завтра
    else:
        offset = random.randint(2, 5)   # 15% - загруженность, до 5 дней
    return call_date + timedelta(days=offset)

def generate_one_call(call_dt, current_date, customer, op,
                      load_norm, op_factor, prob_key, group_key):
    """Генерирует одну строку факта."""
    # 1. Тип проблемы с учётом вероятностей типов
    prob_name = random.choices(
        [p[0] for p in PROBLEMS],
        weights=[p[1] for p in PROBLEMS],
        k=1,
    )[0]
    base_p = next(p[2] for p in PROBLEMS if p[0] == prob_name)   # базовая вероятность решения

    is_internal = (prob_name == "Неработающее оборудование по адресу")   # внутренняя заявка

    # 2. Решаемость и группа назначения
    if is_internal:
        # Внутренняя заявка автоматически закрыта
        resolved = True
        group_name = "Внутренняя заявка"
    else:
        p_res = compute_p_resolved(base_p, op["Category"], load_norm)
        # При успехе заявка закрывается на линии
        if random.random() < p_res:
            resolved = True
            group_name = "Закрыто на линии"
        # Иначе - выбор группы назначения, 5% остаются незакрытыми
        else:
            group_name = pick_assignment_group(customer)
            resolved = random.random() > OPEN_TICKET_PROB

    # 3. Длительность звонка
    duration = compute_duration(
        EXPERIENCE[op["Category"]], resolved,
        is_internal, load_norm, op_factor,
    )

    # 4. Время закрытия и дата выезда
    scheduled_date = None
    resolution_hours = None

    if not resolved:
        # открытый тикет
        pass
    elif group_name == "Закрыто на линии":
        # Решено сразу: длительность звонка + 5–15 мин на оформление
        resolution_hours = round(duration / 3600 + random.uniform(0.08, 0.25), 2)
    elif group_name == "Внутренняя заявка":
        # Внутренняя заявка: закрывается за 4–24 часа
        resolution_hours = round(random.uniform(4, 24), 2)
    elif group_name == "Офисные инженеры":
        # Внутренняя обработка, без выезда
        resolution_hours = round(random.uniform(2, 48), 2)
        scheduled_date = None
    else:
        # Мастер / Восстановительная бригада / Мастер в деревне, назначение даты и расчёт длительности
        scheduled_date = pick_scheduled_date(current_date, group_name)
        close_dt = datetime.combine(scheduled_date, datetime.min.time()) \
                   + timedelta(hours=random.uniform(2, 8))
        resolution_hours = round((close_dt - call_dt).total_seconds() / 3600, 2)

    # 5. Ключи дат
    date_key  = int(current_date.strftime("%Y%m%d"))
    sched_key = int(scheduled_date.strftime("%Y%m%d")) if scheduled_date else None

    return (
        date_key,
        customer["CustomerKey"],
        op["OperatorKey"],
        prob_key[prob_name],
        group_key[group_name],
        call_dt,
        duration,
        resolution_hours,
        1 if resolved else 0,
        sched_key,
    )

# Главный цикл по календарю
def generate_facts(operators, customers, prob_key, group_key):
    rows = []
    current = START_DATE
    total_days = (END_DATE - START_DATE).days + 1
    print(f"Генерация фактов за {total_days} дней…")

    while current <= END_DATE:
        # Объём звонков в зависимости от дня недели, в среднем будни > сб > вс
        dow = current.isoweekday()   # 1=Пн … 7=Вс
        if dow == 6:
            total_calls = random.randint(70, 110)
        elif dow == 7:
            total_calls = random.randint(50, 80)
        else:
            total_calls = random.randint(100, 150)

        # Смена: 4 случайных оператора
        shift_ops = random.sample(operators, 4)

        # Распределение звонков между операторами
        weights = [random.gammavariate(2, 1) for _ in shift_ops]   # гамма-распределение с группировкой в начале и длинным хвостом
        total_w = sum(weights)
        op_loads = [max(1, int(total_calls * w / total_w)) for w in weights]
        op_loads[0] += total_calls - sum(op_loads)   # коррекция суммы

        avg_load = total_calls / 4

        # Генерация звонков для каждого оператора
        for op, load in zip(shift_ops, op_loads):
            op_factor = random.uniform(0.95, 1.05)   # индивидуальный разброс
            load_norm = (load - avg_load) / avg_load   # +0.5 = на 50% выше среднего

            for _ in range(load):
                # Время звонка
                hour = random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
                minute = random.randint(0, 59)
                second = random.randint(0, 59)
                call_dt = datetime(
                    current.year, current.month, current.day,
                    hour, minute, second,
                )

                customer = random.choice(customers)   # выбор клиента

                rows.append(generate_one_call(
                    # Генерация одной записи факта
                    call_dt, current, customer, op,
                    load_norm, op_factor,
                    prob_key, group_key,
                ))

        if current.day == 1:
            print(f"  {current.strftime('%Y-%m')} — накоплено {len(rows)} строк")

        current += timedelta(days=1)

    return rows

# Загрузка в FactTickets
def load_facts(rows):
    print(f"\nЗагрузка {len(rows)} строк в FactTickets...")
    conn = get_connection()
    cursor = conn.cursor()
    try:
        sql = """
            INSERT INTO FactTickets
            (TicketID, DateKey, CustomerKey, OperatorKey,
             ProblemTypeKey, AssignmentGroupKey, CallStartTime,
             CallDurationSeconds, ResolutionTimeHours, Resolved,
             ScheduledDateKey)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        BATCH = 5000
        # Загрузка батчами по 5000 записей
        for i in range(0, len(rows), BATCH):
            # Срез
            chunk = rows[i:i + BATCH]
            data = []
            for j, r in enumerate(chunk, start=i + 1):
                # Генерация TicketID
                call_dt = r[5]
                ticket_id = f"Т-{call_dt.strftime('%Y%m%d')}-{j:06d}"
                data.append((ticket_id,) + r)

            # Запись
            cursor.executemany(sql, data)
            conn.commit()
            print(f"  загружено {min(i + BATCH, len(rows))} / {len(rows)}")

        print("Готово.")
    except pymysql.MySQLError as e:
        # Безопасный откат транзакции при исключении
        conn.rollback()
        print(f"Ошибка: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

# Main
def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Первоначальное чтение
        operators = load_operators(cursor)
        customers = load_customers(cursor)
        prob_key = load_dict(cursor, "DimProblemType", "ProblemTypeKey", "ProblemTypeName")
        group_key = load_dict(cursor, "DimAssignmentGroup", "GroupKey", "GroupName")

        conn.commit()

        print(f"Операторов:       {len(operators)}")
        print(f"Клиентов:         {len(customers)}")
        print(f"Типов проблем:    {len(prob_key)}")
        print(f"Групп назначения: {len(group_key)}")
        print()
    finally:
        cursor.close()
        conn.close()

    # Генерация и запись
    rows = generate_facts(operators, customers, prob_key, group_key)
    load_facts(rows)


if __name__ == "__main__":
    main()