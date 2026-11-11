/*
    Read-only preflight for Migration 030.
    Run only after the reviewed 027 and 029 migrations.
    This script does not repair legacy assignments or modify production data.
*/
SET NOCOUNT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_030_TestRun')) = N'1'
   )
    THROW 53010, 'Preflight 030 is intended for SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.ShiftMaster', N'U') IS NULL
   OR OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionDayRuleHistory', N'U') IS NULL
    THROW 53011, 'A required Shift, Production, or Production Day rule table is missing.', 1;

IF COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID') IS NULL
    THROW 53012, 'Migration 027 is not applied; dbo.PressProduction.ShiftMasterID is missing.', 1;

IF OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NULL
    THROW 53013, 'Migration 029 is not applied; active interval overlap enforcement is missing.', 1;

IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NOT NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ShiftPeriodID') IS NOT NULL
    THROW 53014, 'Migration 030 target objects already exist; inspect the database before proceeding.', 1;

IF (SELECT COUNT_BIG(*) FROM dbo.ShiftMaster WHERE ShiftCode IN ('1', '2')) <> 2
    THROW 53015, 'Migration 030 requires existing logical Shift codes 1 and 2.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM dbo.ProductionDayRuleHistory
    WHERE EffectiveFromDate = '2026-01-01'
      AND DayStartTime = '08:00'
)
    THROW 53016, 'The historical 08:00 Production Day rule effective 2026-01-01 is missing.', 1;

SELECT N'Migration 027 ShiftMasterID column' AS CheckName,
       CASE WHEN COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID') IS NOT NULL
            THEN N'PASS' ELSE N'FAIL' END AS Result
UNION ALL
SELECT N'Migration 029 overlap trigger',
       CASE WHEN OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NOT NULL
            THEN N'PASS' ELSE N'FAIL' END
UNION ALL
SELECT N'Historical 08:00 rule effective 2026-01-01',
       CASE WHEN EXISTS (
           SELECT 1 FROM dbo.ProductionDayRuleHistory
           WHERE EffectiveFromDate = '2026-01-01' AND DayStartTime = '08:00'
       ) THEN N'PASS' ELSE N'FAIL' END;

SELECT pp.PressProductionID, pp.ProductionID, pp.MachineCode, pp.MouldID,
       lot.ProdDate, pp.ShiftMasterID, pp.ProductionStartTime, pp.ProductionEndTime,
       pp.ReleasedAt
FROM dbo.PressProduction AS pp
JOIN dbo.ProductionLot AS lot ON lot.ProductionID = pp.ProductionID
WHERE lot.IsActive = 1 AND pp.ReleasedAt IS NULL
  AND (pp.ProductionStartTime IS NULL OR pp.ProductionEndTime IS NULL)
ORDER BY lot.ProdDate, pp.PressProductionID;
