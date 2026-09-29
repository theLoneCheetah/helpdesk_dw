USE helpdesk_dw;

-- Всего тикетов и общая средняя длительность
SELECT
    COUNT(*)                            AS TotalTickets,
    ROUND(AVG(CallDurationSeconds),0)   AS AvgDurationSec,
    ROUND(AVG(ResolutionTimeHours),2)   AS AvgResolutionHours,
    ROUND(SUM(Resolved)/COUNT(*)*100,1) AS ResolvedPct
FROM FactTickets;

-- Распределение по группам назначения
SELECT
    g.GroupName,
    COUNT(*)                                                        AS TicketsCount,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM FactTickets), 1) AS Pct
FROM FactTickets f
JOIN DimAssignmentGroup g ON f.AssignmentGroupKey = g.GroupKey
GROUP BY g.GroupName
ORDER BY TicketsCount DESC;

-- Распределение по типам проблем
SELECT
    p.ProblemTypeName,
    COUNT(*)                              AS TicketsCount,
    ROUND(AVG(f.CallDurationSeconds),0)   AS AvgDurationSec,
    ROUND(SUM(f.Resolved)/COUNT(*)*100,1) AS ResolvedPct
FROM FactTickets f
JOIN DimProblemType p ON f.ProblemTypeKey = p.ProblemTypeKey
GROUP BY p.ProblemTypeName
ORDER BY TicketsCount DESC;

-- Распределение по операторам
SELECT
    o.Name,
    o.Category,
    COUNT(*)                              AS TicketsCount,
    ROUND(AVG(f.CallDurationSeconds),0)   AS AvgDurationSec,
    ROUND(SUM(f.Resolved)/COUNT(*)*100,1) AS ResolvedPct
FROM FactTickets f
JOIN DimOperator o ON f.OperatorKey = o.OperatorKey
GROUP BY o.Name, o.Category
ORDER BY o.Category DESC, o.Name;

-- Распределение тикетов по дням недели (проверка сезонности)
SELECT
    d.DayName,
    COUNT(*)                             AS TicketsCount,
    ROUND(AVG(f.CallDurationSeconds),0)  AS AvgDurationSec
FROM FactTickets f
JOIN DimDate d ON f.DateKey = d.DateKey
GROUP BY d.DayOfWeek, d.DayName
ORDER BY d.DayOfWeek;

SELECT
    f.OperatorKey,
    o.Name                        AS OperatorName,
    o.Category                    AS OperatorCategory,
    f.DateKey,
    d.FullDate,
    d.DayOfWeek,
    d.DayName,
    COUNT(*)                                                  AS OperatorLoad,
    ROUND(AVG(f.CallDurationSeconds), 1)                      AS AvgCallDuration,
    SUM(CASE WHEN g.GroupName = 'Закрыто на линии' THEN 1 ELSE 0 END)
                                                              AS ResolvedOnLine,
    ROUND(
        SUM(CASE WHEN g.GroupName = 'Закрыто на линии' THEN 1 ELSE 0 END)
        * 100.0 / COUNT(*),
        2
    )                                                         AS ResolvedOnLineRate
FROM FactTickets f
JOIN DimOperator        o ON f.OperatorKey        = o.OperatorKey
JOIN DimDate            d ON f.DateKey            = d.DateKey
JOIN DimAssignmentGroup g ON f.AssignmentGroupKey = g.GroupKey
GROUP BY
    f.OperatorKey, o.Name, o.Category,
    f.DateKey, d.FullDate, d.DayOfWeek, d.DayName
ORDER BY d.FullDate, o.Name;

-- Разбиение "оператор-день" по трём уровням нагрузки
SELECT
    CASE
        WHEN t.OperatorLoad < 20 THEN 'Низкая'
        WHEN t.OperatorLoad < 35 THEN 'Средняя'
        ELSE 'Высокая'
    END AS LoadGroup,
    COUNT(*)                              AS OperatorDays,
    ROUND(AVG(t.OperatorLoad), 1)         AS AvgLoad,
    ROUND(AVG(t.AvgCallDuration), 1)      AS AvgCallDuration,
    ROUND(AVG(t.ResolvedOnLineRate), 2)   AS AvgResolvedOnLineRate
FROM (
    SELECT
        f.OperatorKey,
        f.DateKey,
        COUNT(*)                   AS OperatorLoad,
        AVG(f.CallDurationSeconds) AS AvgCallDuration,
        SUM(CASE WHEN g.GroupName = 'Закрыто на линии' THEN 1 ELSE 0 END)
            * 100.0 / COUNT(*)     AS ResolvedOnLineRate
    FROM FactTickets f
    JOIN DimAssignmentGroup g ON f.AssignmentGroupKey = g.GroupKey
    GROUP BY f.OperatorKey, f.DateKey
) t
GROUP BY LoadGroup
ORDER BY FIELD(LoadGroup, 'Низкая', 'Средняя', 'Высокая');

-- Сводка по категориям операторов
SELECT
    o.Category,
    COUNT(DISTINCT f.OperatorKey)           AS OperatorsCount,
    COUNT(*)                                AS TicketsCount,
    ROUND(AVG(f.CallDurationSeconds), 1)    AS AvgCallDuration,
    ROUND(AVG(f.CallDurationSeconds)/60, 2) AS AvgCallMinutes,
    ROUND(SUM(CASE WHEN g.GroupName = 'Закрыто на линии' THEN 1 ELSE 0 END)
          * 100.0 / COUNT(*), 2)            AS ResolvedOnLineRate
FROM FactTickets f
JOIN DimOperator        o ON f.OperatorKey        = o.OperatorKey
JOIN DimAssignmentGroup g ON f.AssignmentGroupKey = g.GroupKey
GROUP BY o.Category
ORDER BY o.Category DESC;

-- Разбиваем все "оператор-дни" на три равные группы по OperatorLoad:
--   терциль 1 — низкая нагрузка,
--   терциль 2 — средняя,
--   терциль 3 — высокая.

WITH shift_stats AS (
    SELECT
        f.OperatorKey,
        f.DateKey,
        COUNT(*)                                                    AS OperatorLoad,
        AVG(f.CallDurationSeconds)                                  AS AvgCallDuration,
        SUM(CASE WHEN g.GroupName = 'Закрыто на линии' THEN 1 ELSE 0 END)
            * 100.0 / COUNT(*)                                      AS ResolvedOnLineRate
    FROM FactTickets f
    JOIN DimAssignmentGroup g ON f.AssignmentGroupKey = g.GroupKey
    GROUP BY f.OperatorKey, f.DateKey
),
tertiles AS (
    SELECT
        *,
        NTILE(3) OVER (ORDER BY OperatorLoad) AS LoadTertile
    FROM shift_stats
)
SELECT
    LoadTertile,
    COUNT(*)                              AS Shifts,
    ROUND(AVG(OperatorLoad), 1)           AS AvgLoad,
    ROUND(MIN(OperatorLoad), 0)           AS MinLoad,
    ROUND(MAX(OperatorLoad), 0)           AS MaxLoad,
    ROUND(AVG(AvgCallDuration), 1)        AS AvgDurationSec,
    ROUND(AVG(ResolvedOnLineRate), 2)     AS AvgResolvedOnLineRate
FROM tertiles
GROUP BY LoadTertile
ORDER BY LoadTertile;