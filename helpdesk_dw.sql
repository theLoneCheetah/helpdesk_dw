-- ============================================================
-- Хранилище данных для анализа обращений в техподдержку
-- Схема: "Звезда"
-- СУБД: MySQL 8+
-- ============================================================

DROP DATABASE IF EXISTS helpdesk_dw;   -- удаление старой БД для отладки, можно убрать
CREATE DATABASE helpdesk_dw
    CHARACTER SET utf8mb4   -- UTF-8 с поддержкой русских символов
    COLLATE utf8mb4_unicode_ci;   -- правила сравнения и сортировки текста без учёта регистра
USE helpdesk_dw;

-- ------------------------------------------------------------
-- 1. Измерение "Дата"
-- ------------------------------------------------------------
CREATE TABLE DimDate (
    DateKey        INT           NOT NULL,   -- суррогатный ключ
    FullDate       DATE          NOT NULL,
    Year           INT           NOT NULL,
    Quarter        INT           NOT NULL,
    Month          INT           NOT NULL,
    MonthName      VARCHAR(20)   NOT NULL,
    DayOfMonth     INT           NOT NULL,
    DayOfWeek      INT           NOT NULL,
    DayName        VARCHAR(20)   NOT NULL,
    WeekOfYear     INT           NOT NULL,
    IsWeekend      BOOLEAN       NOT NULL,
    PRIMARY KEY (DateKey),
    UNIQUE KEY uq_dimdate_fulldate (FullDate)   -- все значения FullDate должны быть уникальными
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;   -- гарантия использования движка и настроек кодировки

-- ------------------------------------------------------------
-- 2. Измерение "Клиент"
-- ------------------------------------------------------------
CREATE TABLE DimCustomer (
    CustomerKey    INT           NOT NULL AUTO_INCREMENT,   -- суррогатный ключ с автоинкрементом
    CustomerID     VARCHAR(20)   NOT NULL,   -- бизнес-ключ
    Name           VARCHAR(100)  NOT NULL,   -- ФИО
    City           VARCHAR(50)   NOT NULL,
    Street         VARCHAR(100)  NOT NULL,
    House          VARCHAR(20)   NOT NULL,
    Building       VARCHAR(10)   NULL,   -- корпус и квартира необязательны
    Apartment      VARCHAR(10)   NULL,
    IsVillage      BOOLEAN       NOT NULL DEFAULT FALSE,   -- по умолчанию, клиент считается городским
    TariffPlan     VARCHAR(50)   NOT NULL,
    PRIMARY KEY (CustomerKey),
    UNIQUE KEY uq_dimcustomer_id (CustomerID)   -- все значения CustomerID должны быть уникальными
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 3. Измерение "Оператор ТП"
-- ------------------------------------------------------------
CREATE TABLE DimOperator (
    OperatorKey    INT           NOT NULL AUTO_INCREMENT,   -- суррогатный ключ с автоинкрементом
    OperatorID     VARCHAR(20)   NOT NULL,   -- бизнес-ключ
    Name           VARCHAR(100)  NOT NULL,   -- ФИО
    Category       INT           NOT NULL,
    HireDate       DATE          NOT NULL,
    PRIMARY KEY (OperatorKey),
    UNIQUE KEY uq_dimoperator_id (OperatorID),   -- все значения OperatorID должны быть уникальными
    CONSTRAINT chk_operator_category CHECK (Category BETWEEN 1 AND 3)   -- профессиональная категория строго от 1 до 3
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 4. Измерение "Тип проблемы"
-- ------------------------------------------------------------
CREATE TABLE DimProblemType (
    ProblemTypeKey   INT           NOT NULL AUTO_INCREMENT,   -- суррогатный ключ с автоинкрементом
    ProblemTypeName  VARCHAR(200)  NOT NULL,
    PRIMARY KEY (ProblemTypeKey),
    UNIQUE KEY uq_dimproblemtype_name (ProblemTypeName)   -- все значения ProblemTypeName должны быть уникальными
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 5. Измерение "Группа назначения"
-- ------------------------------------------------------------
CREATE TABLE DimAssignmentGroup (
    GroupKey    INT           NOT NULL AUTO_INCREMENT,   -- суррогатный ключ с автоинкрементом
    GroupName   VARCHAR(100)  NOT NULL,
    PRIMARY KEY (GroupKey),
    UNIQUE KEY uq_dimgroup_name (GroupName)   -- все значения GroupName должны быть уникальными
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- 6. Таблица фактов "Тикеты"
-- ------------------------------------------------------------
CREATE TABLE FactTickets (
    TicketKey             INT             NOT NULL AUTO_INCREMENT,   -- суррогатный ключ с автоинкрементом
    TicketID              VARCHAR(20)     NOT NULL,   -- бизнес-ключ
    DateKey               INT             NOT NULL,
    CustomerKey           INT             NOT NULL,
    OperatorKey           INT             NOT NULL,
    ProblemTypeKey        INT             NOT NULL,
    AssignmentGroupKey    INT             NOT NULL,
    CallStartTime         DATETIME        NOT NULL,
    CallDurationSeconds   INT             NOT NULL,
    ResolutionTimeHours   DECIMAL(10,2)   NULL,
    Resolved              BOOLEAN         NOT NULL DEFAULT FALSE,   -- по умолчанию тикет не закрыт
    ScheduledDateKey      INT             NULL,   -- дата заявки на мастера при необходимости
    PRIMARY KEY (TicketKey),
    UNIQUE KEY uq_facttickets_id (TicketID),   -- все значения TicketID должны быть уникальными
    -- Настройка индексов полей внешних ключей для быстрого поиска
    KEY ix_fact_date        (DateKey),
    KEY ix_fact_customer    (CustomerKey),
    KEY ix_fact_operator    (OperatorKey),
    KEY ix_fact_problem     (ProblemTypeKey),
    KEY ix_fact_group       (AssignmentGroupKey),
    KEY ix_fact_scheddate   (ScheduledDateKey),
    -- Настройка внешних ключей: дата, клиент, оператор, тип проблемы, группа назначения, дата заявки
    CONSTRAINT fk_fact_date       FOREIGN KEY (DateKey)            REFERENCES DimDate(DateKey),
    CONSTRAINT fk_fact_customer   FOREIGN KEY (CustomerKey)        REFERENCES DimCustomer(CustomerKey),
    CONSTRAINT fk_fact_operator   FOREIGN KEY (OperatorKey)        REFERENCES DimOperator(OperatorKey),
    CONSTRAINT fk_fact_problem    FOREIGN KEY (ProblemTypeKey)     REFERENCES DimProblemType(ProblemTypeKey),
    CONSTRAINT fk_fact_group      FOREIGN KEY (AssignmentGroupKey) REFERENCES DimAssignmentGroup(GroupKey),
    CONSTRAINT fk_fact_scheddate  FOREIGN KEY (ScheduledDateKey)   REFERENCES DimDate(DateKey)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- Заполнение DimProblemType (8 типов проблем)
-- ------------------------------------------------------------
INSERT INTO DimProblemType (ProblemTypeName) VALUES
    ('Неработающее оборудование по адресу'),
    ('Повреждение кабеля'),
    ('Проверка интернета'),
    ('Низкая скорость'),
    ('Настройка роутера'),
    ('Вопросы IPTV'),
    ('Вопросы по сетевой настройке'),
    ('Дополнительные платные услуги мастера');

-- ------------------------------------------------------------
-- Заполнение DimAssignmentGroup (5 групп назначения)
-- ------------------------------------------------------------
INSERT INTO DimAssignmentGroup (GroupName) VALUES
    ('Закрыто на линии'),
    ('Внутренняя заявка'),
    ('Офисные инженеры'),
    ('Мастер'),
    ('Восстановительная бригада'),
    ('Мастер в деревне');