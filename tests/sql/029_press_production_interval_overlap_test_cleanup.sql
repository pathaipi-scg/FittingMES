SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23_TEST'
    THROW 52910, 'Migration 029 test cleanup may only run in SB23_TEST.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NOT NULL
        DROP TRIGGER dbo.TR_PressProduction_PreventActiveIntervalOverlap;

    IF EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id=OBJECT_ID(N'dbo.PressProduction')
          AND name=N'IX_PressProduction_ActiveMachineInterval'
    )
        DROP INDEX IX_PressProduction_ActiveMachineInterval ON dbo.PressProduction;

    IF EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id=OBJECT_ID(N'dbo.PressProduction')
          AND name=N'IX_PressProduction_ActiveMouldInterval'
    )
        DROP INDEX IX_PressProduction_ActiveMouldInterval ON dbo.PressProduction;

    IF EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE object_id=OBJECT_ID(N'dbo.PressProduction')
          AND name=N'UX_PressProduction_Production_Machine_ShiftActive'
    )
        DROP INDEX UX_PressProduction_Production_Machine_ShiftActive
            ON dbo.PressProduction;

    IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NOT NULL
        DROP TABLE dbo.PressProduction;

    IF OBJECT_ID(N'dbo.ProductionLot', N'U') IS NOT NULL
        DROP TABLE dbo.ProductionLot;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
