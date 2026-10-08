/*
    Read-only preflight for migration 027.
    Existing PressProduction rows remain at unknown Shift (NULL).
    EquipmentTimeEvent rows are inspected but never rewritten here.
*/
SET NOCOUNT ON;

IF DB_NAME() <> N'SB23'
    THROW 52700, 'Preflight 027 is intended for SB23 only.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftMaster', N'U') IS NULL
   OR OBJECT_ID(N'dbo.EquipmentTimeEvent', N'U') IS NULL
    THROW 52701, 'A required table for preflight 027 is missing.', 1;

IF COL_LENGTH(N'dbo.ShiftMaster', N'id') IS NULL
   OR COL_LENGTH(N'dbo.ShiftMaster', N'ShiftCode') IS NULL
   OR COL_LENGTH(N'dbo.ShiftMaster', N'IsActive') IS NULL
   OR COL_LENGTH(N'dbo.EquipmentTimeEvent', N'ProductionID') IS NULL
   OR COL_LENGTH(N'dbo.EquipmentTimeEvent', N'EquipmentCode') IS NULL
   OR COL_LENGTH(N'dbo.EquipmentTimeEvent', N'ShiftID') IS NULL
   OR COL_LENGTH(N'dbo.EquipmentTimeEvent', N'TimeType') IS NULL
   OR COL_LENGTH(N'dbo.EquipmentTimeEvent', N'SourceType') IS NULL
   OR COL_LENGTH(N'dbo.EquipmentTimeEvent', N'DurationMin') IS NULL
    THROW 52703, 'A required preflight 027 column is missing.', 1;

SELECT id AS ShiftMasterID, ShiftCode, ShiftName, IsActive
FROM dbo.ShiftMaster
ORDER BY ShiftCode, IsActive DESC, id;

SELECT N'PressProduction rows' AS CheckName, COUNT_BIG(*) AS TotalRows
FROM dbo.PressProduction
UNION ALL
SELECT N'Active PressProduction rows', COUNT_BIG(*)
FROM dbo.PressProduction
WHERE ReleasedAt IS NULL
UNION ALL
SELECT N'Released PressProduction rows', COUNT_BIG(*)
FROM dbo.PressProduction
WHERE ReleasedAt IS NOT NULL;

IF COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID') IS NULL
BEGIN
    SELECT N'PressProduction rows awaiting unknown Shift' AS CheckName,
           COUNT_BIG(*) AS TotalRows
    FROM dbo.PressProduction;
END
ELSE
BEGIN
    EXEC sys.sp_executesql N'
        SELECT N''PressProduction rows with unknown Shift'' AS CheckName,
               COUNT_BIG(*) AS TotalRows
        FROM dbo.PressProduction
        WHERE ShiftMasterID IS NULL;';
END;

SELECT
    pp.ProductionID,
    pp.MachineCode,
    COUNT_BIG(*) AS AssignmentCount
FROM dbo.PressProduction AS pp
GROUP BY pp.ProductionID, pp.MachineCode
HAVING COUNT_BIG(*) > 1;

SELECT
    pl.ProdDate,
    pp.MouldID,
    COUNT_BIG(*) AS ActiveAssignmentCount,
    COUNT(DISTINCT pp.ProductionID) AS LotCount
FROM dbo.PressProduction AS pp
JOIN dbo.ProductionLot AS pl
    ON pl.ProductionID = pp.ProductionID
WHERE pp.ReleasedAt IS NULL
  AND pp.MouldID IS NOT NULL
GROUP BY pl.ProdDate, pp.MouldID
HAVING COUNT_BIG(*) > 1
ORDER BY pl.ProdDate, pp.MouldID;

SELECT
    legacy_event.TimeEventID AS Shift2TimeEventID,
    legacy_event.ProductionID,
    legacy_event.EquipmentCode,
    legacy_event.TimeType,
    legacy_event.SourceType,
    legacy_event.DurationMin AS Shift2DurationMin,
    press.PressProductionID,
    shift1_event.TimeEventID AS MatchingShift1TimeEventID,
    shift1_event.DurationMin AS MatchingShift1DurationMin
FROM dbo.EquipmentTimeEvent AS legacy_event
JOIN dbo.PressProduction AS press
  ON press.ProductionID = legacy_event.ProductionID
 AND press.MachineCode = legacy_event.EquipmentCode
LEFT JOIN dbo.EquipmentTimeEvent AS shift1_event
  ON shift1_event.ProductionID = legacy_event.ProductionID
 AND shift1_event.EquipmentCode = legacy_event.EquipmentCode
 AND shift1_event.ShiftID = 1
 AND shift1_event.TimeType = legacy_event.TimeType
 AND shift1_event.SourceType = legacy_event.SourceType
WHERE legacy_event.SourceType = 'MANUAL'
  AND legacy_event.ShiftID = 2
ORDER BY legacy_event.ProductionID, legacy_event.EquipmentCode,
         legacy_event.TimeType, legacy_event.TimeEventID;

SELECT
    COUNT_BIG(*) AS LinkedShift2ManualEventCount,
    SUM(CASE WHEN legacy_event.DurationMin IS NULL OR legacy_event.DurationMin <> 0
             THEN CONVERT(bigint, 1) ELSE CONVERT(bigint, 0) END)
        AS NonzeroOrNullLinkedShift2ManualEventCount,
    SUM(CASE WHEN shift1_event.TimeEventID IS NOT NULL THEN CONVERT(bigint, 1) ELSE CONVERT(bigint, 0) END)
        AS Shift1NaturalKeyCollisionCount
FROM dbo.EquipmentTimeEvent AS legacy_event
JOIN dbo.PressProduction AS press
  ON press.ProductionID = legacy_event.ProductionID
 AND press.MachineCode = legacy_event.EquipmentCode
LEFT JOIN dbo.EquipmentTimeEvent AS shift1_event
  ON shift1_event.ProductionID = legacy_event.ProductionID
 AND shift1_event.EquipmentCode = legacy_event.EquipmentCode
 AND shift1_event.ShiftID = 1
 AND shift1_event.TimeType = legacy_event.TimeType
 AND shift1_event.SourceType = legacy_event.SourceType
WHERE legacy_event.SourceType = 'MANUAL'
  AND legacy_event.ShiftID = 2;

SELECT
    COUNT_BIG(*) AS UnlinkedShift2ManualEventCount
FROM dbo.EquipmentTimeEvent AS legacy_event
WHERE legacy_event.SourceType = 'MANUAL'
  AND legacy_event.ShiftID = 2
  AND NOT EXISTS (
      SELECT 1
      FROM dbo.PressProduction AS press
      WHERE press.ProductionID = legacy_event.ProductionID
        AND press.MachineCode = legacy_event.EquipmentCode
  );

SELECT
    i.name AS IndexName,
    i.is_unique AS IsUnique,
    c.name AS KeyColumn,
    ic.key_ordinal AS KeyOrdinal
FROM sys.indexes AS i
JOIN sys.index_columns AS ic
    ON ic.object_id = i.object_id
   AND ic.index_id = i.index_id
JOIN sys.columns AS c
    ON c.object_id = ic.object_id
   AND c.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID(N'dbo.PressProduction')
  AND i.name = N'UX_PressProduction_Production_Machine'
ORDER BY ic.key_ordinal;

SELECT
    c.name AS ShiftMasterIDColumn,
    TYPE_NAME(c.user_type_id) AS DataType,
    c.is_nullable AS IsNullable
FROM sys.columns AS c
WHERE c.object_id = OBJECT_ID(N'dbo.PressProduction')
  AND c.name = N'ShiftMasterID';
