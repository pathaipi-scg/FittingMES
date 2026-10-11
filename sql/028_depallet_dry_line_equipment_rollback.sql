SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.DepalletLineEquipmentMap', N'U') IS NULL
        THROW 52850, 'DepalletLineEquipmentMap is missing.', 1;
    IF OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit', N'U') IS NULL
        THROW 52851, 'DepalletRejectLineMigrationAudit is missing.', 1;

    IF EXISTS (
        SELECT 1
        FROM dbo.DepalletRejectEntry AS entry
        JOIN dbo.DepalletLineEquipmentMap AS mapping
          ON mapping.EquipmentID=entry.LineEquipmentID
        LEFT JOIN dbo.DepalletRejectLineMigrationAudit AS audit
          ON audit.EntryID=entry.id
         AND audit.DryLineEquipmentID=mapping.EquipmentID
        WHERE audit.id IS NULL
    )
        THROW 52852, 'Rollback refused: a non-demo DepalletRejectEntry references a dry-line identity.', 1;

    IF EXISTS (
        SELECT 1
        FROM dbo.DepalletRejectLineMigrationAudit AS audit
        JOIN dbo.DepalletRejectEntry AS entry
          ON entry.id=audit.EntryID
        WHERE entry.LineEquipmentID<>audit.DryLineEquipmentID
    )
        THROW 52853, 'Rollback refused: demo reassignment audit does not match current data.', 1;

    UPDATE entry
    SET LineEquipmentID=audit.OriginalLineEquipmentID
    FROM dbo.DepalletRejectEntry AS entry
    JOIN dbo.DepalletRejectLineMigrationAudit AS audit
      ON audit.EntryID=entry.id;

    DECLARE @DryLineEquipment TABLE (EquipmentID bigint PRIMARY KEY);

    INSERT INTO @DryLineEquipment (EquipmentID)
    SELECT EquipmentID
    FROM dbo.DepalletLineEquipmentMap;

    DROP TABLE dbo.DepalletRejectLineMigrationAudit;

    DELETE FROM dbo.DepalletLineEquipmentMap;

    DELETE equipment
    FROM dbo.EquipmentMaster AS equipment
    JOIN @DryLineEquipment AS dry_line
      ON dry_line.EquipmentID=equipment.id
    WHERE equipment.EquipmentType='DRY_LINE';

    DROP TABLE dbo.DepalletLineEquipmentMap;

    IF EXISTS (
        SELECT 1
        FROM dbo.EquipmentMaster
        WHERE EquipmentType='DRY_LINE'
    )
        THROW 52854, 'Rollback refused: an unmapped DRY_LINE identity remains.', 1;

    IF EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID(N'dbo.EquipmentMaster')
          AND name=N'CK_EquipmentMaster_Type'
    )
        ALTER TABLE dbo.EquipmentMaster
            DROP CONSTRAINT CK_EquipmentMaster_Type;

    ALTER TABLE dbo.EquipmentMaster
        ADD CONSTRAINT CK_EquipmentMaster_Type
        CHECK (EquipmentType IN ('LINE','PRESS'));

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
