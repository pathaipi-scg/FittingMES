SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
    THROW 52720, 'Rollback 027 may only be applied to SB23.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
    THROW 52721, 'dbo.PressProduction is missing; rollback refused.', 1;

IF COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID') IS NULL
    THROW 52722, 'ShiftMasterID is not present; rollback is not applicable.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.PressProduction
    WHERE ShiftMasterID IS NOT NULL
)
    THROW 52723, 'Rollback refused: Shift-aware assignments now contain Shift data. Dropping ShiftMasterID would discard it; restore a pre-migration backup instead.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.PressProduction
    GROUP BY ProductionID, MachineCode
    HAVING COUNT_BIG(*) > 1
)
    THROW 52724, 'Rollback refused: the original ProductionID + MachineCode unique key cannot be restored without changing assignment history.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
      AND name = N'UX_PressProduction_Production_Machine_ShiftActive'
      AND is_unique = 1
)
    THROW 52725, 'Rollback refused: expected Shift-aware active index is missing.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
      AND name = N'UX_PressProduction_Production_Machine'
)
    THROW 52726, 'Rollback refused: legacy index name is already occupied.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    DROP INDEX UX_PressProduction_Production_Machine_ShiftActive
        ON dbo.PressProduction;

    ALTER TABLE dbo.PressProduction
        DROP CONSTRAINT FK_PressProduction_ShiftMaster;

    ALTER TABLE dbo.PressProduction
        DROP COLUMN ShiftMasterID;

    CREATE UNIQUE INDEX UX_PressProduction_Production_Machine
        ON dbo.PressProduction (ProductionID, MachineCode);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
