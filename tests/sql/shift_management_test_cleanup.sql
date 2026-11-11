SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23_TEST'
    THROW 53220, 'Shift Management test cleanup may only run in SB23_TEST.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.vw_DailyMaterialUsageCalcLogical', N'V') IS NOT NULL
        DROP VIEW dbo.vw_DailyMaterialUsageCalcLogical;
    IF OBJECT_ID(N'dbo.vw_DailyMaterialUsageLogical', N'V') IS NOT NULL
        DROP VIEW dbo.vw_DailyMaterialUsageLogical;
    IF OBJECT_ID(N'dbo.vw_DailyProductionQtyLogical', N'V') IS NOT NULL
        DROP VIEW dbo.vw_DailyProductionQtyLogical;
    IF OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NOT NULL
        DROP TRIGGER dbo.TR_PressProduction_PreventActiveIntervalOverlap;

    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
                 AND name = N'IX_PressProduction_ActiveMachineInterval')
        DROP INDEX IX_PressProduction_ActiveMachineInterval ON dbo.PressProduction;
    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
                 AND name = N'IX_PressProduction_ActiveMouldInterval')
        DROP INDEX IX_PressProduction_ActiveMouldInterval ON dbo.PressProduction;
    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
                 AND name = N'UX_PressProduction_Production_Machine_ShiftActive')
        DROP INDEX UX_PressProduction_Production_Machine_ShiftActive
            ON dbo.PressProduction;
    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'dbo.DailyMaterialUsage')
                 AND name = N'UX_DailyMaterialUsage_Date_ShiftMaster')
        DROP INDEX UX_DailyMaterialUsage_Date_ShiftMaster
            ON dbo.DailyMaterialUsage;
    IF EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'dbo.LoggerEvent')
                 AND name = N'IX_LoggerEvent_ProductionDate_ShiftMaster')
        DROP INDEX IX_LoggerEvent_ProductionDate_ShiftMaster
            ON dbo.LoggerEvent;

    IF OBJECT_ID(N'dbo.DailyMaterialUsageDetail', N'U') IS NOT NULL
        DROP TABLE dbo.DailyMaterialUsageDetail;
    IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NOT NULL
        DROP TABLE dbo.PressProduction;
    IF OBJECT_ID(N'dbo.ProductionData', N'U') IS NOT NULL
        DROP TABLE dbo.ProductionData;
    IF OBJECT_ID(N'dbo.ProductionLot', N'U') IS NOT NULL
        DROP TABLE dbo.ProductionLot;
    IF OBJECT_ID(N'dbo.DailyMaterialUsage', N'U') IS NOT NULL
        DROP TABLE dbo.DailyMaterialUsage;
    IF OBJECT_ID(N'dbo.LoggerEvent', N'U') IS NOT NULL
        DROP TABLE dbo.LoggerEvent;
    IF OBJECT_ID(N'dbo.ProductionRejectEntry', N'U') IS NOT NULL
        DROP TABLE dbo.ProductionRejectEntry;
    IF OBJECT_ID(N'dbo.DepalletRejectEntry', N'U') IS NOT NULL
        DROP TABLE dbo.DepalletRejectEntry;
    IF OBJECT_ID(N'dbo.MaterialUsageMaster', N'U') IS NOT NULL
        DROP TABLE dbo.MaterialUsageMaster;

    IF OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NOT NULL
        DROP TABLE dbo.ShiftPeriodVersion;
    IF OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NOT NULL
        DROP TABLE dbo.ShiftPeriodMaster;
    IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NOT NULL
        DROP TABLE dbo.ShiftMasterVersion;
    IF OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NOT NULL
        DROP TABLE dbo.ProductionDateCutoffVersion;
    IF OBJECT_ID(N'dbo.ShiftMaster', N'U') IS NOT NULL
        DROP TABLE dbo.ShiftMaster;
    IF OBJECT_ID(N'dbo.ProductionDayRuleHistory', N'U') IS NOT NULL
        DROP TABLE dbo.ProductionDayRuleHistory;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
