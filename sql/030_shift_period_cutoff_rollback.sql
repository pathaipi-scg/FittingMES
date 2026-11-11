SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_030_TestRun')) = N'1'
   )
    THROW 53020, 'Rollback 030 may only be applied to SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NULL
    THROW 53021, 'Migration 030 objects are missing; rollback refused.', 1;

IF EXISTS (
    SELECT 1 FROM dbo.PressProduction
    WHERE ShiftPeriodID IS NOT NULL
       OR ShiftMasterVersionID IS NOT NULL
       OR ShiftPeriodVersionID IS NOT NULL
       OR ProductionDateCutoffVersionID IS NOT NULL
)
    THROW 53022, 'Rollback refused: production rows reference versioned configuration.', 1;

IF EXISTS (
    SELECT 1 FROM dbo.ProductionLot
    WHERE ShiftMasterID IS NOT NULL OR ProductionDateCutoffVersionID IS NOT NULL
)
    THROW 53024, 'Rollback refused: Production Lot rows reference versioned configuration.', 1;

IF EXISTS (
    SELECT 1 FROM dbo.ShiftPeriodVersion WHERE VersionNumber > 1
    UNION ALL
    SELECT 1 FROM dbo.ShiftMasterVersion WHERE VersionNumber > 1
    UNION ALL
    SELECT 1 FROM dbo.ProductionDateCutoffVersion WHERE VersionNumber > 1
)
    THROW 53023, 'Rollback refused: configuration history contains user changes.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    ALTER TABLE dbo.PressProduction DROP CONSTRAINT FK_PressProduction_ShiftPeriod;
    ALTER TABLE dbo.PressProduction DROP CONSTRAINT FK_PressProduction_ShiftMasterVersion;
    ALTER TABLE dbo.PressProduction DROP CONSTRAINT FK_PressProduction_ShiftPeriodVersion;
    ALTER TABLE dbo.PressProduction DROP CONSTRAINT FK_PressProduction_CutoffVersion;
    ALTER TABLE dbo.ProductionLot DROP CONSTRAINT FK_ProductionLot_ShiftMaster;
    ALTER TABLE dbo.ProductionLot DROP CONSTRAINT FK_ProductionLot_CutoffVersion;
    ALTER TABLE dbo.PressProduction DROP COLUMN
        ShiftPeriodID, ShiftMasterVersionID, ShiftPeriodVersionID,
        ShiftCodeSnapshot, PeriodLabelSnapshot, PeriodStartTimeSnapshot,
        PeriodEndTimeSnapshot, ProductionDateCutoffVersionID,
        ProductionDateCutoffSnapshot;
    ALTER TABLE dbo.ProductionLot DROP COLUMN
        ShiftMasterID, ShiftCodeSnapshot, ProductionDateCutoffVersionID,
        ProductionDateCutoffSnapshot;

    DROP TABLE dbo.ShiftPeriodVersion;
    DROP TABLE dbo.ShiftPeriodMaster;
    DROP TABLE dbo.ProductionDateCutoffVersion;
    DROP TABLE dbo.ShiftMasterVersion;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
