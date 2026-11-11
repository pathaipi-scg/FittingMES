SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_031_TestRun')) = N'1'
   )
    THROW 53120, 'Rollback 031 may only be applied to SB23 or an authorized SB23_TEST session.', 1;

IF EXISTS (SELECT 1 FROM dbo.DailyMaterialUsage WHERE ShiftMasterID IS NOT NULL)
   OR EXISTS (SELECT 1 FROM dbo.LoggerEvent WHERE ShiftMasterID IS NOT NULL)
   OR EXISTS (SELECT 1 FROM dbo.ProductionRejectEntry WHERE ShiftCodeSnapshot IS NOT NULL)
   OR EXISTS (SELECT 1 FROM dbo.DepalletRejectEntry WHERE ShiftCodeSnapshot IS NOT NULL)
    THROW 53121, 'Rollback 031 would discard saved logical Shift identity or snapshots.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.vw_DailyMaterialUsageCalcLogical', N'V') IS NOT NULL
        DROP VIEW dbo.vw_DailyMaterialUsageCalcLogical;
    IF OBJECT_ID(N'dbo.vw_DailyMaterialUsageLogical', N'V') IS NOT NULL
        DROP VIEW dbo.vw_DailyMaterialUsageLogical;
    IF OBJECT_ID(N'dbo.vw_DailyProductionQtyLogical', N'V') IS NOT NULL
        DROP VIEW dbo.vw_DailyProductionQtyLogical;

    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id=OBJECT_ID(N'dbo.DailyMaterialUsage')
                 AND name=N'UX_DailyMaterialUsage_Date_ShiftMaster')
        DROP INDEX UX_DailyMaterialUsage_Date_ShiftMaster
            ON dbo.DailyMaterialUsage;
    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id=OBJECT_ID(N'dbo.LoggerEvent')
                 AND name=N'IX_LoggerEvent_ProductionDate_ShiftMaster')
        DROP INDEX IX_LoggerEvent_ProductionDate_ShiftMaster
            ON dbo.LoggerEvent;

    ALTER TABLE dbo.DailyMaterialUsage
        DROP CONSTRAINT FK_DailyMaterialUsage_ShiftMaster;
    ALTER TABLE dbo.LoggerEvent
        DROP CONSTRAINT FK_LoggerEvent_ShiftMaster;

    ALTER TABLE dbo.DailyMaterialUsage DROP COLUMN ShiftMasterID;
    ALTER TABLE dbo.LoggerEvent DROP COLUMN ShiftMasterID, ShiftCodeSnapshot;
    ALTER TABLE dbo.ProductionRejectEntry DROP COLUMN ShiftCodeSnapshot;
    ALTER TABLE dbo.DepalletRejectEntry DROP COLUMN ShiftCodeSnapshot;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
