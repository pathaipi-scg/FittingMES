SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_028_TestRun')) = N'1'
   )
    THROW 52810, 'Migration 028 may only be applied to SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
    THROW 52811, 'dbo.PressProduction or dbo.ProductionLot is missing.', 1;

IF COL_LENGTH(N'dbo.PressProduction', N'ProductionID') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'MachineCode') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'MouldID') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ReleasedAt') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ProductionStartTime') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ProductionEndTime') IS NULL
   OR COL_LENGTH(N'dbo.ProductionLot', N'ProdDate') IS NULL
   OR COL_LENGTH(N'dbo.ProductionLot', N'IsActive') IS NULL
    THROW 52812, 'A required interval-overlap column is missing.', 1;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes AS i
    WHERE i.object_id = OBJECT_ID(N'dbo.PressProduction')
      AND i.name = N'UX_PressProduction_Production_Machine_ShiftActive'
      AND i.is_unique = 1
      AND i.is_disabled = 0
      AND i.has_filter = 1
      AND i.filter_definition = N'([ReleasedAt] IS NULL AND [ShiftMasterID] IS NOT NULL)'
      AND (
          SELECT COUNT(*)
          FROM sys.index_columns AS ic
          WHERE ic.object_id = i.object_id
            AND ic.index_id = i.index_id
            AND ic.key_ordinal > 0
      ) = 3
      AND EXISTS (
          SELECT 1 FROM sys.index_columns AS ic
          JOIN sys.columns AS c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
          WHERE ic.object_id=i.object_id AND ic.index_id=i.index_id
            AND ic.key_ordinal=1 AND c.name=N'ProductionID'
      )
      AND EXISTS (
          SELECT 1 FROM sys.index_columns AS ic
          JOIN sys.columns AS c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
          WHERE ic.object_id=i.object_id AND ic.index_id=i.index_id
            AND ic.key_ordinal=2 AND c.name=N'MachineCode'
      )
      AND EXISTS (
          SELECT 1 FROM sys.index_columns AS ic
          JOIN sys.columns AS c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
          WHERE ic.object_id=i.object_id AND ic.index_id=i.index_id
            AND ic.key_ordinal=3 AND c.name=N'ShiftMasterID'
      )
)
    THROW 52813, 'The expected active Press/Shift unique index is missing.', 1;

IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID(N'dbo.PressProduction')
      AND name IN (N'IX_PressProduction_ActiveMachineInterval',
                   N'IX_PressProduction_ActiveMouldInterval')
)
   OR OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR') IS NOT NULL
    THROW 52814, 'Migration 028 target objects already exist; refusing to guess prior state.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    DROP INDEX UX_PressProduction_Production_Machine_ShiftActive
        ON dbo.PressProduction;

    CREATE INDEX IX_PressProduction_ActiveMachineInterval
        ON dbo.PressProduction (MachineCode, ProductionStartTime)
        INCLUDE (ProductionID, ProductionEndTime, MouldID, ShiftMasterID)
        WHERE ReleasedAt IS NULL;

    CREATE INDEX IX_PressProduction_ActiveMouldInterval
        ON dbo.PressProduction (MouldID, ProductionStartTime)
        INCLUDE (ProductionID, ProductionEndTime, MachineCode, ShiftMasterID)
        WHERE ReleasedAt IS NULL AND MouldID IS NOT NULL;

    EXEC sys.sp_executesql N'
CREATE TRIGGER dbo.TR_PressProduction_PreventActiveIntervalOverlap
ON dbo.PressProduction
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @changed TABLE (PressProductionID bigint PRIMARY KEY);

    INSERT INTO @changed (PressProductionID)
    SELECT i.PressProductionID
    FROM inserted AS i
    LEFT JOIN deleted AS d
      ON d.PressProductionID = i.PressProductionID
    WHERE d.PressProductionID IS NULL
       OR EXISTS (
            SELECT i.ProductionID, i.MachineCode, i.MouldID,
                   i.ProductionStartTime, i.ProductionEndTime, i.ReleasedAt
            EXCEPT
            SELECT d.ProductionID, d.MachineCode, d.MouldID,
                   d.ProductionStartTime, d.ProductionEndTime, d.ReleasedAt
       );

    IF NOT EXISTS (SELECT 1 FROM @changed)
        RETURN;

    DECLARE @resources TABLE (ResourceName nvarchar(255) PRIMARY KEY);

    INSERT INTO @resources (ResourceName)
    SELECT DISTINCT N''FittingMES.PressMachine.'' + i.MachineCode
    FROM inserted AS i
    JOIN @changed AS c ON c.PressProductionID = i.PressProductionID
    WHERE i.MachineCode IS NOT NULL
    UNION
    SELECT DISTINCT N''FittingMES.PressMachine.'' + d.MachineCode
    FROM deleted AS d
    JOIN @changed AS c ON c.PressProductionID = d.PressProductionID
    WHERE d.MachineCode IS NOT NULL
    UNION
    SELECT DISTINCT N''FittingMES.PressMould.'' + CONVERT(nvarchar(30), i.MouldID)
    FROM inserted AS i
    JOIN @changed AS c ON c.PressProductionID = i.PressProductionID
    WHERE i.MouldID IS NOT NULL
    UNION
    SELECT DISTINCT N''FittingMES.PressMould.'' + CONVERT(nvarchar(30), d.MouldID)
    FROM deleted AS d
    JOIN @changed AS c ON c.PressProductionID = d.PressProductionID
    WHERE d.MouldID IS NOT NULL;

    DECLARE @resource nvarchar(255);
    DECLARE @lock_result int;
    DECLARE resource_cursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT ResourceName FROM @resources ORDER BY ResourceName;

    OPEN resource_cursor;
    FETCH NEXT FROM resource_cursor INTO @resource;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        EXEC @lock_result = sys.sp_getapplock
            @Resource = @resource,
            @LockMode = N''Exclusive'',
            @LockOwner = N''Transaction'',
            @LockTimeout = 10000;
        IF @lock_result < 0
            THROW 52815, N''Could not acquire Press/Mould availability lock.'', 1;
        FETCH NEXT FROM resource_cursor INTO @resource;
    END;
    CLOSE resource_cursor;
    DEALLOCATE resource_cursor;

    -- Application writers acquire these keys before DML. Direct SQL writers
    -- acquire row locks before this AFTER trigger requests the keys. Mixed writers can deadlock;
    -- callers must retry SQL Server error 1205. This
    -- trigger does not guarantee deadlock-free writes.
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN @changed AS c ON c.PressProductionID = i.PressProductionID
        WHERE i.ReleasedAt IS NULL
          AND (i.ProductionStartTime IS NULL
               OR i.ProductionEndTime IS NULL
               OR i.ProductionEndTime <= i.ProductionStartTime)
    )
        THROW 52816, N''Active Press Production requires a valid start and a later end.'', 1;

    IF EXISTS (
        SELECT 1
        FROM inserted AS new_assignment
        JOIN @changed AS changed_assignment
          ON changed_assignment.PressProductionID = new_assignment.PressProductionID
        JOIN dbo.ProductionLot AS new_lot
          ON new_lot.ProductionID = new_assignment.ProductionID
        JOIN dbo.PressProduction AS existing_assignment
          ON existing_assignment.PressProductionID <> new_assignment.PressProductionID
         AND existing_assignment.ReleasedAt IS NULL
        JOIN dbo.ProductionLot AS existing_lot
          ON existing_lot.ProductionID = existing_assignment.ProductionID
         AND existing_lot.ProdDate = new_lot.ProdDate
        WHERE new_assignment.ReleasedAt IS NULL
          AND new_lot.IsActive = 1
          AND existing_lot.IsActive = 1
          AND (new_assignment.MachineCode = existing_assignment.MachineCode
               OR (new_assignment.MouldID IS NOT NULL
                   AND new_assignment.MouldID = existing_assignment.MouldID))
          AND (
              existing_assignment.ProductionStartTime IS NULL
              OR (existing_assignment.ProductionEndTime IS NOT NULL
                  AND existing_assignment.ProductionEndTime
                      <= existing_assignment.ProductionStartTime)
              OR (
                  (new_assignment.ProductionEndTime IS NULL
                   OR existing_assignment.ProductionStartTime
                      < new_assignment.ProductionEndTime)
                  AND
                  (existing_assignment.ProductionEndTime IS NULL
                   OR new_assignment.ProductionStartTime
                      < existing_assignment.ProductionEndTime)
              )
          )
    )
        THROW 52817, N''Press or Mould assignment overlaps an active interval in this Production Day.'', 1;
END;';

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
