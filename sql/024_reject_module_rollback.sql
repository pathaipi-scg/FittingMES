SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF EXISTS (
        SELECT 1
        FROM (VALUES
            (N'dbo.ProductionRejectEntry'),
            (N'dbo.DepalletRejectEntry'),
            (N'dbo.RejectReasonProductFamily'),
            (N'dbo.RejectReason'),
            (N'dbo.RejectSourceScope'),
            (N'dbo.RejectCatalog'),
            (N'dbo.ShiftMaster')
        ) expected(ObjectName)
        WHERE OBJECT_ID(expected.ObjectName,N'U') IS NOT NULL
          AND (
              COL_LENGTH(expected.ObjectName,N'id') IS NULL
              OR COL_LENGTH(expected.ObjectName,N'Rectime') IS NULL
          )
    )
        THROW 52450, 'Rollback refused: a target table does not match the REJECT identity-table shape.', 1;

    IF OBJECT_ID(N'dbo.ProductionRejectEntry',N'U') IS NOT NULL
        DROP TABLE dbo.ProductionRejectEntry;
    IF OBJECT_ID(N'dbo.DepalletRejectEntry',N'U') IS NOT NULL
        DROP TABLE dbo.DepalletRejectEntry;
    IF OBJECT_ID(N'dbo.RejectReasonProductFamily',N'U') IS NOT NULL
        DROP TABLE dbo.RejectReasonProductFamily;
    IF OBJECT_ID(N'dbo.RejectReason',N'U') IS NOT NULL
        DROP TABLE dbo.RejectReason;
    IF OBJECT_ID(N'dbo.RejectSourceScope',N'U') IS NOT NULL
        DROP TABLE dbo.RejectSourceScope;
    IF OBJECT_ID(N'dbo.RejectCatalog',N'U') IS NOT NULL
        DROP TABLE dbo.RejectCatalog;
    IF OBJECT_ID(N'dbo.ShiftMaster',N'U') IS NOT NULL
        DROP TABLE dbo.ShiftMaster;

    IF COL_LENGTH(N'dbo.EquipmentMaster',N'id') IS NOT NULL
    BEGIN
        IF OBJECT_ID(N'dbo.EquipmentMaster',N'U') IS NULL
            THROW 52451, 'Rollback refused: dbo.EquipmentMaster is missing.', 1;

        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id=OBJECT_ID(N'dbo.EquipmentMaster')
              AND name=N'UQ_EquipmentMaster_id'
              AND type=N'UQ'
        )
            THROW 52452, 'Rollback refused: the expected additive EquipmentMaster ID key is missing.', 1;

        IF EXISTS (
            SELECT 1
            FROM sys.foreign_key_columns fkc
            JOIN sys.columns c
              ON c.object_id=fkc.referenced_object_id
             AND c.column_id=fkc.referenced_column_id
            WHERE fkc.referenced_object_id=OBJECT_ID(N'dbo.EquipmentMaster')
              AND c.name=N'id'
        )
            THROW 52453, 'Rollback refused: another object still references EquipmentMaster.id.', 1;

        ALTER TABLE dbo.EquipmentMaster
            DROP CONSTRAINT UQ_EquipmentMaster_id;
        ALTER TABLE dbo.EquipmentMaster
            DROP COLUMN id;
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
