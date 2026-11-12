SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_031_TestRun')) = N'1'
   )
    THROW 53100, 'Migration 031 may only be applied to SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NULL
   OR COL_LENGTH(N'dbo.ProductionLot', N'ShiftMasterID') IS NULL
   OR COL_LENGTH(N'dbo.ProductionLot', N'ShiftCodeSnapshot') IS NULL
   OR OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NULL
    THROW 53101, 'Migration 030 logical Shift snapshots are required.', 1;

IF COL_LENGTH(N'dbo.DailyMaterialUsage', N'ShiftMasterID') IS NOT NULL
   OR COL_LENGTH(N'dbo.LoggerEvent', N'ShiftMasterID') IS NOT NULL
   OR COL_LENGTH(N'dbo.ProductionRejectEntry', N'ShiftCodeSnapshot') IS NOT NULL
   OR COL_LENGTH(N'dbo.DepalletRejectEntry', N'ShiftCodeSnapshot') IS NOT NULL
   OR OBJECT_ID(N'dbo.vw_DailyProductionQtyLogical', N'V') IS NOT NULL
    THROW 53102, 'Migration 031 target objects already exist; inspect the database before proceeding.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM dbo.ProductionDayRuleHistory
    WHERE EffectiveFromDate = '2026-01-01'
      AND DayStartTime = '08:00'
)
    THROW 53103, 'The historical 08:00 Production Day rule effective 2026-01-01 is missing.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.ShiftMasterVersion
    WHERE EffectiveFromDate > EffectiveToDate
)
    THROW 53104, 'Invalid effective-dated Shift version range detected.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM dbo.ProductionDayRuleHistory
    WHERE EffectiveFromDate = '2026-01-01'
      AND DayStartTime = '08:00'
)
    THROW 53105, 'The historical 08:00 Production Day rule effective 2026-01-01 is missing.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM dbo.ProductionDateCutoffVersion
    WHERE CutoffTime = '07:00'
)
    THROW 53106, 'The initial effective-dated 07:00 Production Date cutoff is missing.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    ALTER TABLE dbo.DailyMaterialUsage
        ADD ShiftMasterID bigint NULL;
    ALTER TABLE dbo.LoggerEvent
        ADD ShiftMasterID bigint NULL,
            ShiftCodeSnapshot varchar(10) NULL;
    ALTER TABLE dbo.ProductionRejectEntry
        ADD ShiftCodeSnapshot varchar(10) NULL;
    ALTER TABLE dbo.DepalletRejectEntry
        ADD ShiftCodeSnapshot varchar(10) NULL;

    EXEC sys.sp_executesql N'
ALTER TABLE dbo.DailyMaterialUsage
    ADD CONSTRAINT FK_DailyMaterialUsage_ShiftMaster
        FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id);
ALTER TABLE dbo.LoggerEvent
    ADD CONSTRAINT FK_LoggerEvent_ShiftMaster
        FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id);

CREATE UNIQUE INDEX UX_DailyMaterialUsage_Date_ShiftMaster
    ON dbo.DailyMaterialUsage (ReportDate, ShiftMasterID)
    WHERE ShiftMasterID IS NOT NULL;
CREATE INDEX IX_LoggerEvent_ProductionDate_ShiftMaster
    ON dbo.LoggerEvent (ProductionDate, ShiftMasterID)
    INCLUDE (DurationMin, StopId)
    WHERE ShiftMasterID IS NOT NULL;';

    EXEC sys.sp_executesql N'
CREATE VIEW dbo.vw_DailyProductionQtyLogical
AS
WITH Resolved AS (
    SELECT
        L.ProdDate AS ReportDate,
        COALESCE(L.ShiftMasterID, historical.ShiftMasterID, current_shift.id)
            AS ShiftMasterID,
        CASE WHEN L.ShiftMasterID IS NULL
                  AND historical.ShiftMasterID IS NULL
                  AND current_shift.id IS NULL
             THEN COALESCE(L.ShiftCodeSnapshot, L.Shift)
             ELSE NULL END AS LegacyShiftKey,
        COALESCE(L.ShiftCodeSnapshot, L.Shift) AS ShiftCode,
        D.CounterQty,
        D.CuringQty
    FROM dbo.ProductionLot AS L
    INNER JOIN dbo.ProductionData AS D
        ON D.ProductionID = L.ProductionID
    OUTER APPLY (
        SELECT TOP (1) V.ShiftMasterID
        FROM dbo.ShiftMasterVersion AS V
        WHERE V.ShiftCode = COALESCE(L.ShiftCodeSnapshot, L.Shift)
          AND V.EffectiveFromDate <= L.ProdDate
          AND (V.EffectiveToDate IS NULL OR V.EffectiveToDate >= L.ProdDate)
        ORDER BY V.EffectiveFromDate DESC, V.VersionNumber DESC
    ) AS historical
    LEFT JOIN dbo.ShiftMaster AS current_shift
        ON current_shift.ShiftCode = COALESCE(L.ShiftCodeSnapshot, L.Shift)
    WHERE L.IsActive = 1
)
SELECT
    ReportDate,
    ShiftMasterID,
    MAX(ShiftCode) AS Shift,
    SUM(CAST(CounterQty AS bigint)) AS CounterQty,
    SUM(CAST(CuringQty AS bigint)) AS CuringQty,
    COUNT_BIG(*) AS LotCount
FROM Resolved
GROUP BY ReportDate, ShiftMasterID, LegacyShiftKey;';

    EXEC sys.sp_executesql N'
CREATE VIEW dbo.vw_DailyMaterialUsageLogical
AS
SELECT
    H.MaterialUsageID,
    H.ReportDate,
    COALESCE(H.ShiftMasterID, historical.ShiftMasterID, current_shift.id)
        AS ShiftMasterID,
    H.Shift AS ShiftCodeSnapshot,
    D.MaterialUsageCode,
    M.MaterialNameTH,
    M.MaterialNameEN,
    M.Unit,
    M.SortOrder,
    M.APIFieldCode,
    M.UsageType,
    D.Qty AS RawQty,
    D.SourceType,
    D.Remark
FROM dbo.DailyMaterialUsage AS H
INNER JOIN dbo.DailyMaterialUsageDetail AS D
    ON D.MaterialUsageID = H.MaterialUsageID
INNER JOIN dbo.MaterialUsageMaster AS M
    ON M.MaterialUsageCode = D.MaterialUsageCode
OUTER APPLY (
    SELECT TOP (1) V.ShiftMasterID
    FROM dbo.ShiftMasterVersion AS V
    WHERE V.ShiftCode = H.Shift
      AND V.EffectiveFromDate <= H.ReportDate
      AND (V.EffectiveToDate IS NULL OR V.EffectiveToDate >= H.ReportDate)
    ORDER BY V.EffectiveFromDate DESC, V.VersionNumber DESC
) AS historical
LEFT JOIN dbo.ShiftMaster AS current_shift
    ON current_shift.ShiftCode = H.Shift;';

    EXEC sys.sp_executesql N'
CREATE VIEW dbo.vw_DailyMaterialUsageCalcLogical
AS
SELECT
    U.MaterialUsageID,
    U.ReportDate,
    U.ShiftMasterID,
    U.ShiftCodeSnapshot AS Shift,
    U.MaterialUsageCode,
    U.MaterialNameTH,
    U.MaterialNameEN,
    U.Unit,
    U.SortOrder,
    U.APIFieldCode,
    U.UsageType,
    U.RawQty,
    P.CounterQty,
    P.CuringQty,
    P.LotCount,
    CASE WHEN U.UsageType = ''MATERIAL''
         THEN CAST(U.RawQty * 1000.0 / NULLIF(P.CounterQty, 0) AS decimal(18,3))
         ELSE NULL END AS QtyPer1000Counter,
    CASE WHEN U.UsageType = ''MATERIAL''
         THEN CAST(U.RawQty * 1000.0 / NULLIF(P.CuringQty, 0) AS decimal(18,3))
         ELSE NULL END AS QtyPer1000Curing,
    CASE WHEN U.UsageType = ''CONSUMABLE''
         THEN CAST(P.CounterQty * 1.0 / NULLIF(U.RawQty, 0) AS decimal(18,3))
         ELSE NULL END AS CounterPerUnit,
    U.SourceType,
    U.Remark
FROM dbo.vw_DailyMaterialUsageLogical AS U
LEFT JOIN dbo.vw_DailyProductionQtyLogical AS P
    ON P.ReportDate = U.ReportDate
   AND (
       (U.ShiftMasterID IS NOT NULL AND P.ShiftMasterID = U.ShiftMasterID)
       OR (U.ShiftMasterID IS NULL AND P.ShiftMasterID IS NULL
           AND P.Shift = U.ShiftCodeSnapshot)
   );';

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
