SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_028_TestRun')) = N'1'
   )
    THROW 52820, 'Rollback 028 may only be applied to SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
    THROW 52821, 'dbo.PressProduction is missing; rollback refused.', 1;

IF OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NULL
    THROW 52822, 'The interval-overlap trigger is missing; rollback is not applicable.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
      AND name = N'UX_PressProduction_Production_Machine_ShiftActive'
)
    THROW 52823, 'Rollback refused: the original index name is already occupied.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.PressProduction
    WHERE ReleasedAt IS NULL
      AND ShiftMasterID IS NOT NULL
    GROUP BY ProductionID, MachineCode, ShiftMasterID
    HAVING COUNT_BIG(*) > 1
)
    THROW 52824, 'Rollback refused: sequential active assignments share a Lot/Press/Shift key.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    DROP TRIGGER dbo.TR_PressProduction_PreventActiveIntervalOverlap;

    DROP INDEX IX_PressProduction_ActiveMachineInterval
        ON dbo.PressProduction;

    DROP INDEX IX_PressProduction_ActiveMouldInterval
        ON dbo.PressProduction;

    CREATE UNIQUE INDEX UX_PressProduction_Production_Machine_ShiftActive
        ON dbo.PressProduction (ProductionID, MachineCode, ShiftMasterID)
        WHERE ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
