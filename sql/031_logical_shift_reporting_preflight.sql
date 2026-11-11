SET NOCOUNT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_031_TestRun')) = N'1'
   )
    THROW 53110, 'Preflight 031 is intended for SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NULL
   OR COL_LENGTH(N'dbo.ProductionLot', N'ShiftMasterID') IS NULL
   OR COL_LENGTH(N'dbo.ProductionLot', N'ShiftCodeSnapshot') IS NULL
   OR OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NULL
    THROW 53111, 'Migration 030 is not applied; logical Shift snapshot prerequisites are missing.', 1;

IF COL_LENGTH(N'dbo.DailyMaterialUsage', N'ShiftMasterID') IS NOT NULL
   OR COL_LENGTH(N'dbo.LoggerEvent', N'ShiftMasterID') IS NOT NULL
   OR COL_LENGTH(N'dbo.ProductionRejectEntry', N'ShiftCodeSnapshot') IS NOT NULL
   OR COL_LENGTH(N'dbo.DepalletRejectEntry', N'ShiftCodeSnapshot') IS NOT NULL
   OR OBJECT_ID(N'dbo.vw_DailyProductionQtyLogical', N'V') IS NOT NULL
    THROW 53112, 'Migration 031 target objects already exist; inspect the database before proceeding.', 1;

SELECT N'ProductionDate historical 08:00 rule' AS CheckName,
       COUNT_BIG(*) AS MatchingRows
FROM dbo.ProductionDayRuleHistory
WHERE EffectiveFromDate = '2026-01-01'
  AND DayStartTime = '08:00'
UNION ALL
SELECT N'Initial configurable 07:00 cutoff version', COUNT_BIG(*)
FROM dbo.ProductionDateCutoffVersion
WHERE CutoffTime = '07:00'
UNION ALL
SELECT N'ProductionLot rows without ShiftMasterID snapshot', COUNT_BIG(*)
FROM dbo.ProductionLot
WHERE ShiftMasterID IS NULL
UNION ALL
SELECT N'Usage rows with legacy Shift string', COUNT_BIG(*)
FROM dbo.DailyMaterialUsage
WHERE ShiftMasterID IS NULL
UNION ALL
SELECT N'LOGGER rows with legacy ShiftID only', COUNT_BIG(*)
FROM dbo.LoggerEvent
WHERE ShiftMasterID IS NULL;

SELECT ShiftMasterID, ShiftCode, EffectiveFromDate, EffectiveToDate,
       VersionNumber, IsActive
FROM dbo.ShiftMasterVersion
ORDER BY ShiftMasterID, EffectiveFromDate, VersionNumber;

SELECT ShiftPeriodID, ShiftMasterID, PeriodLabel, StartTime, EndTime,
       EffectiveFromDate, EffectiveToDate, IsActive
FROM dbo.ShiftPeriodVersion
ORDER BY ShiftMasterID, EffectiveFromDate, DisplayOrder;

SELECT N'Manual usage duplicate logical keys' AS CheckName,
       ReportDate, ShiftMasterID, COUNT_BIG(*) AS DuplicateCount
FROM dbo.DailyMaterialUsage
WHERE ShiftMasterID IS NOT NULL
GROUP BY ReportDate, ShiftMasterID
HAVING COUNT_BIG(*) > 1;
