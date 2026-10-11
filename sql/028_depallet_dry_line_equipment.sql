SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    DECLARE @LockResult int;
    EXEC @LockResult = sys.sp_getapplock
        @Resource=N'FittingMES.Migration.028.DepalletDryLine',
        @LockMode='Exclusive',
        @LockOwner='Transaction',
        @LockTimeout=0;
    IF @LockResult < 0
        THROW 52800, 'Migration 028 could not acquire its application lock.', 1;

    IF OBJECT_ID(N'dbo.EquipmentMaster', N'U') IS NULL
        THROW 52801, 'Required dbo.EquipmentMaster table is missing.', 1;
    IF OBJECT_ID(N'dbo.Fitting_MainMachine', N'U') IS NULL
        THROW 52802, 'Required dbo.Fitting_MainMachine table is missing.', 1;
    IF OBJECT_ID(N'dbo.Fitting_SubMachine', N'U') IS NULL
        THROW 52803, 'Required dbo.Fitting_SubMachine table is missing.', 1;
    IF OBJECT_ID(N'dbo.DepalletRejectEntry', N'U') IS NULL
        THROW 52804, 'Required dbo.DepalletRejectEntry table is missing.', 1;
    IF COL_LENGTH(N'dbo.EquipmentMaster', N'id') IS NULL
        THROW 52805, 'EquipmentMaster.id is required by the REJECT schema.', 1;

    DECLARE @MainMachineCount int;
    DECLARE @MainMachineId int;
    DECLARE @MainMachineNo int;
    DECLARE @SubMachineCount int;

    SELECT @MainMachineCount=COUNT(*)
    FROM dbo.Fitting_MainMachine WITH (UPDLOCK,HOLDLOCK)
    WHERE Machine=N'LINE(dry)' AND IsActive=1 AND No>0;

    IF @MainMachineCount <> 1
        THROW 52806, 'Exactly one active LINE(dry) main-machine master is required.', 1;

    SELECT @MainMachineId=McId,@MainMachineNo=No
    FROM dbo.Fitting_MainMachine WITH (UPDLOCK,HOLDLOCK)
    WHERE Machine=N'LINE(dry)' AND IsActive=1 AND No>0;

    SELECT @SubMachineCount=COUNT(*)
    FROM dbo.Fitting_SubMachine WITH (UPDLOCK,HOLDLOCK)
    WHERE Equipment=N'LINE(dry)'
      AND McId=@MainMachineId
      AND IsActive=1
      AND IsRelated=1
      AND No BETWEEN 1 AND @MainMachineNo;

    IF @SubMachineCount <> @MainMachineNo
        THROW 52807, 'LINE(dry) sub-machine instances do not match the active main-machine count.', 1;

    IF EXISTS (
        SELECT No
        FROM dbo.Fitting_SubMachine WITH (UPDLOCK,HOLDLOCK)
        WHERE Equipment=N'LINE(dry)'
          AND McId=@MainMachineId
          AND IsActive=1
          AND IsRelated=1
          AND No BETWEEN 1 AND @MainMachineNo
        GROUP BY No
        HAVING COUNT(*) <> 1
    )
        THROW 52808, 'LINE(dry) instance numbers are ambiguous.', 1;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID(N'dbo.EquipmentMaster')
          AND name=N'CK_EquipmentMaster_Type'
    )
        THROW 52809, 'EquipmentMaster type constraint is missing.', 1;

    DECLARE @TypeDefinition nvarchar(max);
    SELECT @TypeDefinition=definition
    FROM sys.check_constraints
    WHERE parent_object_id=OBJECT_ID(N'dbo.EquipmentMaster')
      AND name=N'CK_EquipmentMaster_Type';

    IF @TypeDefinition NOT LIKE N'%DRY_LINE%'
    BEGIN
        ALTER TABLE dbo.EquipmentMaster
            DROP CONSTRAINT CK_EquipmentMaster_Type;
        ALTER TABLE dbo.EquipmentMaster
            ADD CONSTRAINT CK_EquipmentMaster_Type
            CHECK (EquipmentType IN ('LINE','PRESS','DRY_LINE'));
    END;

    IF OBJECT_ID(N'dbo.DepalletLineEquipmentMap', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.DepalletLineEquipmentMap
        (
            id bigint IDENTITY(1,1) NOT NULL
                CONSTRAINT PK_DepalletLineEquipmentMap PRIMARY KEY,
            Rectime datetime NOT NULL
                CONSTRAINT DF_DepalletLineEquipmentMap_Rectime DEFAULT (GETDATE()),
            MainMachineMcId int NOT NULL,
            SubMcId int NOT NULL,
            InstanceNo int NOT NULL,
            EquipmentID bigint NOT NULL,
            IsActive bit NOT NULL
                CONSTRAINT DF_DepalletLineEquipmentMap_IsActive DEFAULT (1),
            CONSTRAINT UQ_DepalletLineEquipmentMap_Instance
                UNIQUE (MainMachineMcId,SubMcId,InstanceNo),
            CONSTRAINT UQ_DepalletLineEquipmentMap_Equipment
                UNIQUE (EquipmentID),
            CONSTRAINT CK_DepalletLineEquipmentMap_InstanceNo
                CHECK (InstanceNo > 0),
            CONSTRAINT FK_DepalletLineEquipmentMap_MainMachine
                FOREIGN KEY (MainMachineMcId)
                REFERENCES dbo.Fitting_MainMachine(McId),
            CONSTRAINT FK_DepalletLineEquipmentMap_SubMachine
                FOREIGN KEY (SubMcId)
                REFERENCES dbo.Fitting_SubMachine(SubMcId),
            CONSTRAINT FK_DepalletLineEquipmentMap_Equipment
                FOREIGN KEY (EquipmentID)
                REFERENCES dbo.EquipmentMaster(id)
        );
    END
    ELSE
    BEGIN
        IF COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'id') IS NULL
           OR COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'Rectime') IS NULL
           OR COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'MainMachineMcId') IS NULL
           OR COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'SubMcId') IS NULL
           OR COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'InstanceNo') IS NULL
           OR COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'EquipmentID') IS NULL
           OR COL_LENGTH(N'dbo.DepalletLineEquipmentMap', N'IsActive') IS NULL
            THROW 52810, 'Existing DepalletLineEquipmentMap has an invalid shape.', 1;

        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletLineEquipmentMap')
              AND name=N'PK_DepalletLineEquipmentMap'
        )
            THROW 52811, 'Existing dry-line mapping primary key is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletLineEquipmentMap')
              AND name=N'UQ_DepalletLineEquipmentMap_Instance'
        )
            THROW 52812, 'Existing dry-line instance uniqueness constraint is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletLineEquipmentMap')
              AND name=N'UQ_DepalletLineEquipmentMap_Equipment'
        )
            THROW 52813, 'Existing dry-line EquipmentMaster uniqueness constraint is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletLineEquipmentMap')
              AND name=N'FK_DepalletLineEquipmentMap_MainMachine'
        )
            THROW 52814, 'Existing dry-line main-machine foreign key is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletLineEquipmentMap')
              AND name=N'FK_DepalletLineEquipmentMap_SubMachine'
        )
            THROW 52815, 'Existing dry-line sub-machine foreign key is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletLineEquipmentMap')
              AND name=N'FK_DepalletLineEquipmentMap_Equipment'
        )
            THROW 52816, 'Existing dry-line EquipmentMaster foreign key is missing.', 1;
    END;

    IF OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit', N'U') IS NULL
    BEGIN
        CREATE TABLE dbo.DepalletRejectLineMigrationAudit
        (
            id bigint IDENTITY(1,1) NOT NULL
                CONSTRAINT PK_DepalletRejectLineMigrationAudit PRIMARY KEY,
            Rectime datetime NOT NULL
                CONSTRAINT DF_DepalletRejectLineMigrationAudit_Rectime DEFAULT (GETDATE()),
            EntryID bigint NOT NULL,
            OriginalLineEquipmentID bigint NOT NULL,
            DryLineEquipmentID bigint NOT NULL,
            CONSTRAINT UQ_DepalletRejectLineMigrationAudit_Entry
                UNIQUE (EntryID),
            CONSTRAINT FK_DepalletRejectLineMigrationAudit_Entry
                FOREIGN KEY (EntryID)
                REFERENCES dbo.DepalletRejectEntry(id),
            CONSTRAINT FK_DepalletRejectLineMigrationAudit_OriginalLine
                FOREIGN KEY (OriginalLineEquipmentID)
                REFERENCES dbo.EquipmentMaster(id),
            CONSTRAINT FK_DepalletRejectLineMigrationAudit_DryLine
                FOREIGN KEY (DryLineEquipmentID)
                REFERENCES dbo.EquipmentMaster(id)
        );
    END
    ELSE
    BEGIN
        IF COL_LENGTH(N'dbo.DepalletRejectLineMigrationAudit', N'id') IS NULL
           OR COL_LENGTH(N'dbo.DepalletRejectLineMigrationAudit', N'Rectime') IS NULL
           OR COL_LENGTH(N'dbo.DepalletRejectLineMigrationAudit', N'EntryID') IS NULL
           OR COL_LENGTH(N'dbo.DepalletRejectLineMigrationAudit', N'OriginalLineEquipmentID') IS NULL
           OR COL_LENGTH(N'dbo.DepalletRejectLineMigrationAudit', N'DryLineEquipmentID') IS NULL
            THROW 52817, 'Existing Depallet Reject migration audit has an invalid shape.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit')
              AND name=N'PK_DepalletRejectLineMigrationAudit'
        )
            THROW 52818, 'Existing Depallet Reject migration audit primary key is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.key_constraints
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit')
              AND name=N'UQ_DepalletRejectLineMigrationAudit_Entry'
        )
            THROW 52819, 'Existing Depallet Reject migration audit uniqueness constraint is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit')
              AND name=N'FK_DepalletRejectLineMigrationAudit_Entry'
        )
            THROW 52820, 'Existing Depallet Reject migration audit EntryID foreign key is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit')
              AND name=N'FK_DepalletRejectLineMigrationAudit_OriginalLine'
        )
            THROW 52821, 'Existing Depallet Reject migration audit original-line foreign key is missing.', 1;
        IF NOT EXISTS (
            SELECT 1
            FROM sys.foreign_keys
            WHERE parent_object_id=OBJECT_ID(N'dbo.DepalletRejectLineMigrationAudit')
              AND name=N'FK_DepalletRejectLineMigrationAudit_DryLine'
        )
            THROW 52822, 'Existing Depallet Reject migration audit dry-line foreign key is missing.', 1;
    END;

    DECLARE @DryLineSeeds TABLE
    (
        InstanceNo int NOT NULL PRIMARY KEY,
        EquipmentCode varchar(20) NOT NULL UNIQUE,
        EquipmentName nvarchar(200) NOT NULL,
        MainMachineMcId int NOT NULL,
        SubMcId int NOT NULL
    );

    INSERT INTO @DryLineSeeds
        (InstanceNo,EquipmentCode,EquipmentName,MainMachineMcId,SubMcId)
    SELECT sub_machine.No,
           CONCAT('LINE_DRY',sub_machine.No),
           CONCAT(sub_machine.Equipment,N' ',sub_machine.No),
           main_machine.McId,
           sub_machine.SubMcId
    FROM dbo.Fitting_SubMachine AS sub_machine WITH (UPDLOCK,HOLDLOCK)
    JOIN dbo.Fitting_MainMachine AS main_machine WITH (UPDLOCK,HOLDLOCK)
      ON main_machine.McId=sub_machine.McId
     AND main_machine.McId=@MainMachineId
     AND main_machine.Machine=N'LINE(dry)'
     AND main_machine.IsActive=1
     AND sub_machine.No BETWEEN 1 AND main_machine.No
    WHERE sub_machine.Equipment=N'LINE(dry)'
      AND sub_machine.IsActive=1
      AND sub_machine.IsRelated=1;

    IF EXISTS (
        SELECT 1
        FROM @DryLineSeeds AS seed
        JOIN dbo.EquipmentMaster AS equipment WITH (UPDLOCK,HOLDLOCK)
          ON equipment.EquipmentCode=seed.EquipmentCode
        WHERE equipment.EquipmentType<>'DRY_LINE'
           OR equipment.IsActive<>1
    )
        THROW 52816, 'An existing dry-line EquipmentMaster business key has an invalid type or state.', 1;

    INSERT INTO dbo.EquipmentMaster
        (EquipmentCode,EquipmentName,EquipmentType,DisplayOrder,
         IsActive,CreatedAt,UpdatedAt)
    SELECT seed.EquipmentCode,seed.EquipmentName,'DRY_LINE',
           1000+seed.InstanceNo,1,GETDATE(),GETDATE()
    FROM @DryLineSeeds AS seed
    WHERE NOT EXISTS (
        SELECT 1
        FROM dbo.EquipmentMaster AS equipment WITH (UPDLOCK,HOLDLOCK)
        WHERE equipment.EquipmentCode=seed.EquipmentCode
    );

    IF EXISTS (
        SELECT 1
        FROM @DryLineSeeds AS seed
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=seed.EquipmentCode
        WHERE equipment.EquipmentType<>'DRY_LINE'
           OR equipment.IsActive<>1
    )
        THROW 52817, 'Dry-line EquipmentMaster identity validation failed.', 1;

    IF EXISTS (
        SELECT 1
        FROM @DryLineSeeds AS seed
        JOIN dbo.DepalletLineEquipmentMap AS mapping
          ON mapping.MainMachineMcId=seed.MainMachineMcId
         AND mapping.SubMcId=seed.SubMcId
         AND mapping.InstanceNo=seed.InstanceNo
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.EquipmentCode=seed.EquipmentCode
        WHERE mapping.IsActive<>1 OR mapping.EquipmentID<>equipment.id
    )
        THROW 52818, 'An existing dry-line mapping is inconsistent.', 1;

    INSERT INTO dbo.DepalletLineEquipmentMap
        (MainMachineMcId,SubMcId,InstanceNo,EquipmentID,IsActive)
    SELECT seed.MainMachineMcId,seed.SubMcId,seed.InstanceNo,
           equipment.id,1
    FROM @DryLineSeeds AS seed
    JOIN dbo.EquipmentMaster AS equipment
      ON equipment.EquipmentCode=seed.EquipmentCode
     AND equipment.EquipmentType='DRY_LINE'
     AND equipment.IsActive=1
    WHERE NOT EXISTS (
        SELECT 1
        FROM dbo.DepalletLineEquipmentMap AS mapping WITH (UPDLOCK,HOLDLOCK)
        WHERE mapping.MainMachineMcId=seed.MainMachineMcId
          AND mapping.SubMcId=seed.SubMcId
          AND mapping.InstanceNo=seed.InstanceNo
    );

    IF EXISTS (
        SELECT 1
        FROM @DryLineSeeds AS seed
        LEFT JOIN dbo.DepalletLineEquipmentMap AS mapping
          ON mapping.MainMachineMcId=seed.MainMachineMcId
         AND mapping.SubMcId=seed.SubMcId
         AND mapping.InstanceNo=seed.InstanceNo
         AND mapping.IsActive=1
        WHERE mapping.id IS NULL
    )
        THROW 52819, 'Not every active LINE(dry) instance has an active equipment mapping.', 1;

    IF EXISTS (
        SELECT 1
        FROM dbo.DepalletLineEquipmentMap AS mapping
        JOIN dbo.Fitting_MainMachine AS main_machine
          ON main_machine.McId=mapping.MainMachineMcId
         AND main_machine.McId=@MainMachineId
        WHERE mapping.IsActive=1
          AND NOT EXISTS (
              SELECT 1
              FROM @DryLineSeeds AS seed
              WHERE seed.MainMachineMcId=mapping.MainMachineMcId
                AND seed.SubMcId=mapping.SubMcId
                AND seed.InstanceNo=mapping.InstanceNo
          )
    )
        THROW 52820, 'An unexpected active dry-line mapping exists.', 1;

    DECLARE @LegacyLineId bigint;
    DECLARE @DryLineId bigint;
    DECLARE @LegacyLineCount int;
    DECLARE @DryLineCount int;
    DECLARE @AuditCount int;
    DECLARE @TotalDepalletCount int;

    IF (
        SELECT COUNT(*)
        FROM dbo.EquipmentMaster WITH (UPDLOCK,HOLDLOCK)
        WHERE EquipmentCode='LINE2' AND EquipmentType='LINE'
    ) <> 1
        THROW 52823, 'Exactly one legacy LINE2 EquipmentMaster identity is required for demo reassignment.', 1;

    SELECT @LegacyLineId=id
    FROM dbo.EquipmentMaster WITH (UPDLOCK,HOLDLOCK)
    WHERE EquipmentCode='LINE2' AND EquipmentType='LINE';

    IF (
        SELECT COUNT(*)
        FROM dbo.DepalletLineEquipmentMap AS mapping
        JOIN dbo.Fitting_MainMachine AS main_machine
          ON main_machine.McId=mapping.MainMachineMcId
         AND main_machine.McId=@MainMachineId
         AND main_machine.IsActive=1
        JOIN dbo.Fitting_SubMachine AS sub_machine
          ON sub_machine.SubMcId=mapping.SubMcId
         AND sub_machine.McId=main_machine.McId
         AND sub_machine.No=mapping.InstanceNo
         AND sub_machine.No=1
         AND sub_machine.IsActive=1
         AND sub_machine.IsRelated=1
        JOIN dbo.EquipmentMaster AS equipment
          ON equipment.id=mapping.EquipmentID
         AND equipment.EquipmentType='DRY_LINE'
         AND equipment.IsActive=1
        WHERE mapping.IsActive=1
          AND mapping.InstanceNo=1
    ) <> 1
        THROW 52824, 'Exactly one active LINE(dry) instance 1 mapping is required for demo reassignment.', 1;

    SELECT @DryLineId=equipment.id
    FROM dbo.DepalletLineEquipmentMap AS mapping
    JOIN dbo.Fitting_MainMachine AS main_machine
      ON main_machine.McId=mapping.MainMachineMcId
     AND main_machine.McId=@MainMachineId
    JOIN dbo.Fitting_SubMachine AS sub_machine
      ON sub_machine.SubMcId=mapping.SubMcId
     AND sub_machine.McId=main_machine.McId
     AND sub_machine.No=mapping.InstanceNo
     AND sub_machine.No=1
    JOIN dbo.EquipmentMaster AS equipment
      ON equipment.id=mapping.EquipmentID
     AND equipment.EquipmentType='DRY_LINE'
    WHERE mapping.IsActive=1 AND mapping.InstanceNo=1;

    SELECT @TotalDepalletCount=COUNT(*),
           @LegacyLineCount=COALESCE(SUM(CASE WHEN LineEquipmentID=@LegacyLineId THEN 1 ELSE 0 END),0),
           @DryLineCount=COALESCE(SUM(CASE WHEN LineEquipmentID=@DryLineId THEN 1 ELSE 0 END),0)
    FROM dbo.DepalletRejectEntry WITH (UPDLOCK,HOLDLOCK);

    SELECT @AuditCount=COUNT(*)
    FROM dbo.DepalletRejectLineMigrationAudit WITH (UPDLOCK,HOLDLOCK);

    IF @TotalDepalletCount <> 4
        THROW 52825, 'Demo reassignment requires exactly four existing Depallet Reject records.', 1;

    IF @LegacyLineCount=4 AND @DryLineCount=0
    BEGIN
        IF @AuditCount <> 0
            THROW 52826, 'Demo reassignment audit is partially populated.', 1;

        INSERT INTO dbo.DepalletRejectLineMigrationAudit
            (EntryID,OriginalLineEquipmentID,DryLineEquipmentID)
        SELECT id,@LegacyLineId,@DryLineId
        FROM dbo.DepalletRejectEntry WITH (UPDLOCK,HOLDLOCK)
        WHERE LineEquipmentID=@LegacyLineId;

        IF @@ROWCOUNT <> 4
            THROW 52827, 'Demo reassignment did not audit exactly four records.', 1;

        UPDATE dbo.DepalletRejectEntry
        SET LineEquipmentID=@DryLineId
        WHERE LineEquipmentID=@LegacyLineId;

        IF @@ROWCOUNT <> 4
            THROW 52828, 'Demo reassignment did not update exactly four records.', 1;
    END
    ELSE IF @LegacyLineCount=0 AND @DryLineCount=4
    BEGIN
        IF @AuditCount <> 4
            THROW 52829, 'Completed demo reassignment has an invalid audit row count.', 1;

        IF EXISTS (
            SELECT 1
            FROM dbo.DepalletRejectLineMigrationAudit AS audit
            JOIN dbo.DepalletRejectEntry AS entry
              ON entry.id=audit.EntryID
            WHERE audit.OriginalLineEquipmentID<>@LegacyLineId
               OR audit.DryLineEquipmentID<>@DryLineId
               OR entry.LineEquipmentID<>@DryLineId
        )
            THROW 52830, 'Completed demo reassignment audit does not match current data.', 1;
    END
    ELSE
        THROW 52831, 'Depallet Reject demo data is in a partial or conflicting reassignment state.', 1;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
