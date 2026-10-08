SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
    THROW 52710, 'Migration 027 may only be applied to SB23.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftMaster', N'U') IS NULL
    THROW 52711, 'A required Press Production, Production Lot, or Shift table is missing.', 1;

IF COL_LENGTH(N'dbo.PressProduction', N'ProductionID') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'MachineCode') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'MouldID') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ReleasedAt') IS NULL
   OR COL_LENGTH(N'dbo.ShiftMaster', N'id') IS NULL
    THROW 52712, 'A required migration 027 column is missing.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.ShiftMaster')
      AND name = N'id'
      AND TYPE_NAME(user_type_id) <> N'bigint'
)
    THROW 52713, 'dbo.ShiftMaster.id must be bigint.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes AS i
    JOIN sys.index_columns AS ic
      ON ic.object_id = i.object_id
     AND ic.index_id = i.index_id
    JOIN sys.columns AS c
      ON c.object_id = ic.object_id
     AND c.column_id = ic.column_id
    WHERE i.object_id = OBJECT_ID(N'dbo.ShiftMaster')
      AND i.is_unique = 1
      AND ic.key_ordinal = 1
      AND c.name = N'id'
      AND NOT EXISTS (
          SELECT 1
          FROM sys.index_columns AS extra
          WHERE extra.object_id = i.object_id
            AND extra.index_id = i.index_id
            AND extra.key_ordinal > 1
      )
)
    THROW 52714, 'dbo.ShiftMaster.id must have a unique key for the foreign key.', 1;

IF COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID') IS NOT NULL
   OR EXISTS (
       SELECT 1
       FROM sys.indexes
       WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
         AND name = N'UX_PressProduction_Production_Machine_ShiftActive'
   )
   OR EXISTS (
       SELECT 1
       FROM sys.foreign_keys
       WHERE parent_object_id = OBJECT_ID(N'dbo.PressProduction')
         AND name = N'FK_PressProduction_ShiftMaster'
   )
    THROW 52715, 'Migration 027 target column or objects already exist; refusing to guess prior state.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes AS i
    WHERE i.object_id = OBJECT_ID(N'dbo.PressProduction')
      AND i.name = N'UX_PressProduction_Production_Machine'
      AND i.is_unique = 1
      AND i.is_disabled = 0
      AND i.has_filter = 0
      AND (
          SELECT COUNT(*)
          FROM sys.index_columns AS ic
          WHERE ic.object_id = i.object_id
            AND ic.index_id = i.index_id
            AND ic.key_ordinal > 0
      ) = 2
      AND EXISTS (
          SELECT 1
          FROM sys.index_columns AS ic
          JOIN sys.columns AS c
            ON c.object_id = ic.object_id
           AND c.column_id = ic.column_id
          WHERE ic.object_id = i.object_id
            AND ic.index_id = i.index_id
            AND ic.key_ordinal = 1
            AND c.name = N'ProductionID'
      )
      AND EXISTS (
          SELECT 1
          FROM sys.index_columns AS ic
          JOIN sys.columns AS c
            ON c.object_id = ic.object_id
           AND c.column_id = ic.column_id
          WHERE ic.object_id = i.object_id
            AND ic.index_id = i.index_id
            AND ic.key_ordinal = 2
            AND c.name = N'MachineCode'
      )
)
    THROW 52716, 'The existing PressProduction unique index does not match the expected ProductionID + MachineCode key.', 1;

IF EXISTS (
    SELECT 1
    FROM dbo.PressProduction
    GROUP BY ProductionID, MachineCode
    HAVING COUNT_BIG(*) > 1
)
    THROW 52717, 'Existing PressProduction rows conflict on ProductionID + MachineCode.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    ALTER TABLE dbo.PressProduction
        ADD ShiftMasterID bigint NULL;

    EXEC sys.sp_executesql N'
        ALTER TABLE dbo.PressProduction
            ADD CONSTRAINT FK_PressProduction_ShiftMaster
            FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id);';

    DROP INDEX UX_PressProduction_Production_Machine
        ON dbo.PressProduction;

    EXEC sys.sp_executesql N'
        CREATE UNIQUE INDEX UX_PressProduction_Production_Machine_ShiftActive
            ON dbo.PressProduction (ProductionID, MachineCode, ShiftMasterID)
            WHERE ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL;';

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
