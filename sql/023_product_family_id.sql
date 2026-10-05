-- Preserve ProductFamilyMaster.ProductFamilyTH as nvarchar(200) NULL; this migration does not alter it.
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH('dbo.ProductFamilyMaster', 'ProductFamilyID') IS NOT NULL
        THROW 52300, 'ProductFamilyID migration appears to have already run.', 1;

    IF EXISTS (
        SELECT 1
        FROM dbo.ProductFamilyMaster
        WHERE LotPrefixLetter IS NULL
           OR LotPrefixLetter NOT BETWEEN 'A' AND 'Z'
    )
        THROW 52301, 'ProductFamilyMaster contains an invalid LotPrefixLetter.', 1;

    CREATE TABLE #PF_PreMigrationCounts (
        ObjectName sysname NOT NULL PRIMARY KEY,
        RowTotal bigint NOT NULL
    );
    INSERT INTO #PF_PreMigrationCounts(ObjectName,RowTotal)
    SELECT 'ProductFamilyMaster',COUNT_BIG(*) FROM dbo.ProductFamilyMaster
    UNION ALL SELECT 'ProductCodeMaster',COUNT_BIG(*) FROM dbo.ProductCodeMaster
    UNION ALL SELECT 'MaterialProductMap',COUNT_BIG(*) FROM dbo.MaterialProductMap
    UNION ALL SELECT 'MaterialProductMapHistory',COUNT_BIG(*) FROM dbo.MaterialProductMapHistory
    UNION ALL SELECT 'MouldMaster',COUNT_BIG(*) FROM dbo.MouldMaster
    UNION ALL SELECT 'PressProductCapability',COUNT_BIG(*) FROM dbo.PressProductCapability
    UNION ALL SELECT 'PressProductCapabilityHistory',COUNT_BIG(*) FROM dbo.PressProductCapabilityHistory
    UNION ALL SELECT 'ProductionLot',COUNT_BIG(*) FROM dbo.ProductionLot
    UNION ALL SELECT 'Depallet',COUNT_BIG(*) FROM dbo.Depallet;

    CREATE TABLE #PF_PostMigrationCounts (
        ObjectName sysname NOT NULL PRIMARY KEY,
        RowTotal bigint NOT NULL
    );
    CREATE TABLE #PF_PreMigrationSnapshots (
        ObjectName sysname NOT NULL,
        ColumnName sysname NOT NULL,
        RawValue varbinary(8000) NULL,
        RawLength int NOT NULL,
        Occurrences bigint NOT NULL
    );
    CREATE TABLE #PF_PostMigrationSnapshots (
        ObjectName sysname NOT NULL,
        ColumnName sysname NOT NULL,
        RawValue varbinary(8000) NULL,
        RawLength int NOT NULL,
        Occurrences bigint NOT NULL
    );
    INSERT INTO #PF_PreMigrationSnapshots(ObjectName,ColumnName,RawValue,RawLength,Occurrences)
    SELECT 'ProductFamilyMaster','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.ProductFamilyMaster GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'ProductFamilyMaster','ProductFamilyTH',CONVERT(varbinary(8000),ProductFamilyTH),
        ISNULL(DATALENGTH(ProductFamilyTH),-1),COUNT_BIG(*)
    FROM dbo.ProductFamilyMaster GROUP BY CONVERT(varbinary(8000),ProductFamilyTH),ISNULL(DATALENGTH(ProductFamilyTH),-1)
    UNION ALL
    SELECT 'ProductCodeMaster','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.ProductCodeMaster GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'MaterialProductMap','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.MaterialProductMap GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'MaterialProductMapHistory','OldProductFamily',CONVERT(varbinary(8000),OldProductFamily),
        ISNULL(DATALENGTH(OldProductFamily),-1),COUNT_BIG(*)
    FROM dbo.MaterialProductMapHistory GROUP BY CONVERT(varbinary(8000),OldProductFamily),ISNULL(DATALENGTH(OldProductFamily),-1)
    UNION ALL
    SELECT 'MaterialProductMapHistory','NewProductFamily',CONVERT(varbinary(8000),NewProductFamily),
        ISNULL(DATALENGTH(NewProductFamily),-1),COUNT_BIG(*)
    FROM dbo.MaterialProductMapHistory GROUP BY CONVERT(varbinary(8000),NewProductFamily),ISNULL(DATALENGTH(NewProductFamily),-1)
    UNION ALL
    SELECT 'MaterialProductMapHistory','OldProductCode',CONVERT(varbinary(8000),OldProductCode),
        ISNULL(DATALENGTH(OldProductCode),-1),COUNT_BIG(*)
    FROM dbo.MaterialProductMapHistory GROUP BY CONVERT(varbinary(8000),OldProductCode),ISNULL(DATALENGTH(OldProductCode),-1)
    UNION ALL
    SELECT 'MaterialProductMapHistory','NewProductCode',CONVERT(varbinary(8000),NewProductCode),
        ISNULL(DATALENGTH(NewProductCode),-1),COUNT_BIG(*)
    FROM dbo.MaterialProductMapHistory GROUP BY CONVERT(varbinary(8000),NewProductCode),ISNULL(DATALENGTH(NewProductCode),-1)
    UNION ALL
    SELECT 'MouldMaster','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.MouldMaster GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'PressProductCapability','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.PressProductCapability GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'PressProductCapabilityHistory','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.PressProductCapabilityHistory GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'ProductionLot','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.ProductionLot GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'ProductionLot','ProductCode',CONVERT(varbinary(8000),ProductCode),
        ISNULL(DATALENGTH(ProductCode),-1),COUNT_BIG(*)
    FROM dbo.ProductionLot GROUP BY CONVERT(varbinary(8000),ProductCode),ISNULL(DATALENGTH(ProductCode),-1)
    UNION ALL
    SELECT 'Depallet','ProductFamily',CONVERT(varbinary(8000),ProductFamily),
        ISNULL(DATALENGTH(ProductFamily),-1),COUNT_BIG(*)
    FROM dbo.Depallet GROUP BY CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
    UNION ALL
    SELECT 'Depallet','ProductCode',CONVERT(varbinary(8000),ProductCode),
        ISNULL(DATALENGTH(ProductCode),-1),COUNT_BIG(*)
    FROM dbo.Depallet GROUP BY CONVERT(varbinary(8000),ProductCode),ISNULL(DATALENGTH(ProductCode),-1);

    ALTER TABLE dbo.ProductFamilyMaster
        ADD ProductFamilyID int IDENTITY(1,1) NOT NULL;

    ALTER TABLE dbo.ProductCodeMaster ADD ProductFamilyID int NULL;
    ALTER TABLE dbo.MaterialProductMap ADD ProductFamilyID int NULL;
    ALTER TABLE dbo.MaterialProductMapHistory
        ADD OldProductFamilyID int NULL, NewProductFamilyID int NULL;
    ALTER TABLE dbo.MouldMaster ADD ProductFamilyID int NULL;
    ALTER TABLE dbo.PressProductCapability ADD ProductFamilyID int NULL;
    ALTER TABLE dbo.PressProductCapabilityHistory ADD ProductFamilyID int NULL;
    ALTER TABLE dbo.ProductionLot ADD ProductFamilyID int NULL;

    EXEC sys.sp_executesql N'
    IF EXISTS (
        SELECT 1 FROM dbo.ProductCodeMaster pcm
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=pcm.ProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(pcm.ProductFamily)
        WHERE pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.MaterialProductMap m
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=m.ProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(m.ProductFamily)
        WHERE m.ProductFamily IS NOT NULL AND pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.MaterialProductMapHistory h
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=h.OldProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(h.OldProductFamily)
        WHERE h.OldProductFamily IS NOT NULL AND pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.MaterialProductMapHistory h
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=h.NewProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(h.NewProductFamily)
        WHERE h.NewProductFamily IS NOT NULL AND pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.MouldMaster m
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=m.ProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(m.ProductFamily)
        WHERE pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.PressProductCapability c
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=c.ProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(c.ProductFamily)
        WHERE pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.PressProductCapabilityHistory h
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=h.ProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(h.ProductFamily)
        WHERE pf.ProductFamilyID IS NULL
    ) OR EXISTS (
        SELECT 1 FROM dbo.ProductionLot l
        LEFT JOIN dbo.ProductFamilyMaster pf
          ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=l.ProductFamily COLLATE Latin1_General_100_BIN2
         AND DATALENGTH(pf.ProductFamily)=DATALENGTH(l.ProductFamily)
        WHERE l.ProductFamily IS NOT NULL AND pf.ProductFamilyID IS NULL
    )
        THROW 52302, ''A non-NULL family value has no exact ProductFamilyMaster match.'', 1;

    UPDATE pcm SET ProductFamilyID=pf.ProductFamilyID
    FROM dbo.ProductCodeMaster pcm
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=pcm.ProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(pcm.ProductFamily);
    UPDATE m SET ProductFamilyID=pf.ProductFamilyID
    FROM dbo.MaterialProductMap m
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=m.ProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(m.ProductFamily);
    UPDATE h SET OldProductFamilyID=pf.ProductFamilyID
    FROM dbo.MaterialProductMapHistory h
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=h.OldProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(h.OldProductFamily);
    UPDATE h SET NewProductFamilyID=pf.ProductFamilyID
    FROM dbo.MaterialProductMapHistory h
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=h.NewProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(h.NewProductFamily);
    UPDATE m SET ProductFamilyID=pf.ProductFamilyID
    FROM dbo.MouldMaster m
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=m.ProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(m.ProductFamily);
    UPDATE c SET ProductFamilyID=pf.ProductFamilyID
    FROM dbo.PressProductCapability c
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=c.ProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(c.ProductFamily);
    UPDATE h SET ProductFamilyID=pf.ProductFamilyID
    FROM dbo.PressProductCapabilityHistory h
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=h.ProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(h.ProductFamily);
    UPDATE l SET ProductFamilyID=pf.ProductFamilyID
    FROM dbo.ProductionLot l
    JOIN dbo.ProductFamilyMaster pf
      ON pf.ProductFamily COLLATE Latin1_General_100_BIN2=l.ProductFamily COLLATE Latin1_General_100_BIN2
     AND DATALENGTH(pf.ProductFamily)=DATALENGTH(l.ProductFamily);

    IF EXISTS (SELECT 1 FROM dbo.ProductCodeMaster WHERE ProductFamilyID IS NULL)
       OR EXISTS (SELECT 1 FROM dbo.MouldMaster WHERE ProductFamilyID IS NULL)
       OR EXISTS (SELECT 1 FROM dbo.PressProductCapability WHERE ProductFamilyID IS NULL)
       OR EXISTS (SELECT 1 FROM dbo.PressProductCapabilityHistory WHERE ProductFamilyID IS NULL)
       OR EXISTS (SELECT 1 FROM dbo.ProductCodeMaster GROUP BY ProductFamilyID,ProductCode HAVING COUNT(*)>1)
       OR EXISTS (SELECT 1 FROM dbo.MaterialProductMap m WHERE m.ProductFamilyID IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM dbo.ProductCodeMaster p
                                  WHERE p.ProductFamilyID=m.ProductFamilyID AND p.ProductCode=m.ProductCode))
       OR EXISTS (SELECT 1 FROM dbo.MouldMaster m WHERE NOT EXISTS
                  (SELECT 1 FROM dbo.ProductCodeMaster p
                   WHERE p.ProductFamilyID=m.ProductFamilyID AND p.ProductCode=m.ProductCode))
       OR EXISTS (SELECT 1 FROM dbo.PressProductCapability c WHERE NOT EXISTS
                  (SELECT 1 FROM dbo.ProductCodeMaster p
                   WHERE p.ProductFamilyID=c.ProductFamilyID AND p.ProductCode=c.ProductCode))
       OR EXISTS (SELECT 1 FROM dbo.PressProductCapabilityHistory h WHERE NOT EXISTS
                  (SELECT 1 FROM dbo.ProductCodeMaster p
                   WHERE p.ProductFamilyID=h.ProductFamilyID AND p.ProductCode=h.ProductCode))
       OR EXISTS (SELECT 1 FROM dbo.ProductionLot l WHERE l.ProductFamilyID IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM dbo.ProductCodeMaster p
                                  WHERE p.ProductFamilyID=l.ProductFamilyID AND p.ProductCode=l.ProductCode))
        THROW 52303, ''ProductFamilyID backfill or family-scoped ProductCode validation failed.'', 1;
    ';

    IF OBJECT_ID('dbo.FK_ProductCodeMaster_Family','F') IS NOT NULL
        ALTER TABLE dbo.ProductCodeMaster DROP CONSTRAINT FK_ProductCodeMaster_Family;
    IF OBJECT_ID('dbo.FK_MaterialProductMap_FamilyCode','F') IS NOT NULL
        ALTER TABLE dbo.MaterialProductMap DROP CONSTRAINT FK_MaterialProductMap_FamilyCode;
    IF OBJECT_ID('dbo.FK_MouldMaster_Product','F') IS NOT NULL
        ALTER TABLE dbo.MouldMaster DROP CONSTRAINT FK_MouldMaster_Product;
    IF OBJECT_ID('dbo.FK_PressProductCapability_Product','F') IS NOT NULL
        ALTER TABLE dbo.PressProductCapability DROP CONSTRAINT FK_PressProductCapability_Product;
    IF OBJECT_ID('dbo.FK_PressProductCapabilityHistory_Product','F') IS NOT NULL
        ALTER TABLE dbo.PressProductCapabilityHistory DROP CONSTRAINT FK_PressProductCapabilityHistory_Product;
    IF OBJECT_ID('dbo.FK_ProductionLot_FamilyCode','F') IS NOT NULL
        ALTER TABLE dbo.ProductionLot DROP CONSTRAINT FK_ProductionLot_FamilyCode;

    EXEC sys.sp_executesql N'
    ALTER TABLE dbo.ProductCodeMaster ALTER COLUMN ProductFamilyID int NOT NULL;
    ALTER TABLE dbo.MouldMaster ALTER COLUMN ProductFamilyID int NOT NULL;
    ALTER TABLE dbo.PressProductCapability ALTER COLUMN ProductFamilyID int NOT NULL;
    ALTER TABLE dbo.PressProductCapabilityHistory ALTER COLUMN ProductFamilyID int NOT NULL;

    ALTER TABLE dbo.ProductFamilyMaster DROP CONSTRAINT PK_ProductFamilyMaster;
    ALTER TABLE dbo.ProductFamilyMaster DROP CONSTRAINT CK_ProductFamilyMaster_Prefix;
    ALTER TABLE dbo.ProductFamilyMaster ADD CONSTRAINT PK_ProductFamilyMaster
        PRIMARY KEY CLUSTERED (ProductFamilyID);
    ALTER TABLE dbo.ProductFamilyMaster ADD CONSTRAINT UQ_ProductFamilyMaster_ProductFamily
        UNIQUE NONCLUSTERED (ProductFamily);
    ALTER TABLE dbo.ProductFamilyMaster ADD CONSTRAINT CK_ProductFamilyMaster_LotPrefixLetter
        CHECK (LotPrefixLetter BETWEEN ''A'' AND ''Z'');

    ALTER TABLE dbo.ProductCodeMaster DROP CONSTRAINT PK_ProductCodeMaster;
    ALTER TABLE dbo.ProductCodeMaster ADD CONSTRAINT PK_ProductCodeMaster
        PRIMARY KEY CLUSTERED (ProductFamilyID,ProductCode);
    ALTER TABLE dbo.ProductCodeMaster ADD CONSTRAINT FK_ProductCodeMaster_FamilyID
        FOREIGN KEY (ProductFamilyID) REFERENCES dbo.ProductFamilyMaster(ProductFamilyID);

    ALTER TABLE dbo.MaterialProductMap ADD CONSTRAINT FK_MaterialProductMap_FamilyIDCode
        FOREIGN KEY (ProductFamilyID,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamilyID,ProductCode);
    ALTER TABLE dbo.MouldMaster ADD CONSTRAINT FK_MouldMaster_ProductID
        FOREIGN KEY (ProductFamilyID,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamilyID,ProductCode);
    ALTER TABLE dbo.PressProductCapability DROP CONSTRAINT PK_PressProductCapability;
    ALTER TABLE dbo.PressProductCapability ADD CONSTRAINT PK_PressProductCapability
        PRIMARY KEY CLUSTERED (PressEquipmentCode,ProductFamilyID,ProductCode);
    ALTER TABLE dbo.PressProductCapability ADD CONSTRAINT FK_PressProductCapability_ProductID
        FOREIGN KEY (ProductFamilyID,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamilyID,ProductCode);
    ALTER TABLE dbo.PressProductCapabilityHistory ADD CONSTRAINT FK_PressProductCapabilityHistory_ProductID
        FOREIGN KEY (ProductFamilyID,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamilyID,ProductCode);
    ALTER TABLE dbo.ProductionLot ADD CONSTRAINT FK_ProductionLot_FamilyIDCode
        FOREIGN KEY (ProductFamilyID,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamilyID,ProductCode);

    DROP INDEX IX_PressProductCapability_Product ON dbo.PressProductCapability;
    CREATE INDEX IX_PressProductCapability_Product
        ON dbo.PressProductCapability(ProductFamilyID,ProductCode,IsActive)
        INCLUDE (PressEquipmentCode);
    DROP INDEX IX_PressProductCapabilityHistory_PressProduct ON dbo.PressProductCapabilityHistory;
    CREATE INDEX IX_PressProductCapabilityHistory_PressProduct
        ON dbo.PressProductCapabilityHistory(PressEquipmentCode,ProductFamilyID,ProductCode,ChangedAt);

    DROP INDEX UX_ProductionLot_FamilyLotNo ON dbo.ProductionLot;
    DROP INDEX UX_ProductionLot_FamilySequence ON dbo.ProductionLot;
    DROP INDEX UX_ProductionLot_LegacyLotNo ON dbo.ProductionLot;
    DROP INDEX UX_ProductionLot_LegacySequence ON dbo.ProductionLot;
    CREATE UNIQUE INDEX UX_ProductionLot_FamilyLotNo
        ON dbo.ProductionLot(ProductFamilyID,LotNo)
        WHERE IsActive=1 AND ProductFamilyID IS NOT NULL;
    CREATE UNIQUE INDEX UX_ProductionLot_FamilySequence
        ON dbo.ProductionLot(ProductFamilyID,ProductCode,SequenceMonth,RunningNo)
        WHERE IsActive=1 AND ProductFamilyID IS NOT NULL;
    CREATE UNIQUE INDEX UX_ProductionLot_LegacyLotNo
        ON dbo.ProductionLot(LotNo)
        WHERE IsActive=1 AND ProductFamilyID IS NULL;
    CREATE UNIQUE INDEX UX_ProductionLot_LegacySequence
        ON dbo.ProductionLot(LotPrefix,RunningNo)
        WHERE IsActive=1 AND ProductFamilyID IS NULL;
    ';

    EXEC(N'CREATE OR ALTER VIEW dbo.vw_MouldList AS
        SELECT m.MouldID,m.MouldNo,m.MouldName,m.ProductFamilyID,
            pf.ProductFamily,m.ProductCode,pcm.ProductName,m.Status,
            m.CurrentReconditionNo,l.CurrentAge,l.LifetimeAge,l.UsageRecordCount,
            l.LastUsageDateTime,m.Remark,m.CreatedAt,m.UpdatedAt
        FROM dbo.MouldMaster m
        JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamilyID=m.ProductFamilyID
        JOIN dbo.ProductCodeMaster pcm
          ON pcm.ProductFamilyID=m.ProductFamilyID AND pcm.ProductCode=m.ProductCode
        LEFT JOIN dbo.vw_MouldLifeSummary l ON l.MouldID=m.MouldID;');

    EXEC(N'CREATE OR ALTER VIEW dbo.vw_PressMcCapabilityMatrix AS
        SELECT p.PressCode,p.PressName,p.CurrentLine,p.CurrentLineName,
            pf.ProductFamilyID,pf.ProductFamily,pc.ProductCode,pc.ProductName,pc.ProductNameTH,
            CAST(CASE WHEN cap.IsActive=1 THEN 1 ELSE 0 END AS bit) AS CanProduce,
            cap.StandardSpeed
        FROM dbo.vw_PressMcPressList p
        CROSS JOIN dbo.ProductCodeMaster pc
        JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamilyID=pc.ProductFamilyID
        LEFT JOIN dbo.PressProductCapability cap
          ON cap.PressEquipmentCode=p.PressCode
         AND cap.ProductFamilyID=pc.ProductFamilyID
         AND cap.ProductCode=pc.ProductCode
        WHERE pc.IsActive=1;');

    EXEC(N'CREATE OR ALTER PROCEDURE dbo.sp_Mould_Register
        @MouldName nvarchar(200), @ProductFamilyID int, @ProductCode varchar(2),
        @Remark nvarchar(2000)=NULL, @ChangedBy nvarchar(100)=NULL
    AS
    BEGIN
        SET NOCOUNT ON; SET XACT_ABORT ON;
        DECLARE @MouldID bigint,@Seq bigint,@MouldNo varchar(50),@ProductFamily varchar(30);
        IF NULLIF(LTRIM(RTRIM(@MouldName)),N'''') IS NULL
            THROW 50001, ''MouldName is required.'', 1;
        SELECT @ProductFamily=ProductFamily FROM dbo.ProductFamilyMaster
        WHERE ProductFamilyID=@ProductFamilyID;
        IF @ProductFamily IS NULL OR NOT EXISTS
            (SELECT 1 FROM dbo.ProductCodeMaster
             WHERE ProductFamilyID=@ProductFamilyID AND ProductCode=@ProductCode)
            THROW 50002, ''Invalid ProductFamilyID / ProductCode.'', 1;
        BEGIN TRANSACTION;
        SET @Seq=NEXT VALUE FOR dbo.Seq_MouldNo;
        SET @MouldNo=''M''+RIGHT(''000000''+CONVERT(varchar(20),@Seq),6);
        INSERT INTO dbo.MouldMaster
            (MouldNo,MouldName,ProductFamily,ProductFamilyID,ProductCode,Status,CurrentReconditionNo,Remark)
        VALUES (@MouldNo,@MouldName,@ProductFamily,@ProductFamilyID,@ProductCode,''ACTIVE'',0,@Remark);
        SET @MouldID=SCOPE_IDENTITY();
        INSERT INTO dbo.MouldStatusHistory
            (MouldID,FromStatus,ToStatus,ChangeType,Remark,ChangedBy)
        VALUES (@MouldID,NULL,''ACTIVE'',''REGISTER'',N''New mould registered'',@ChangedBy);
        COMMIT TRANSACTION;
        SELECT * FROM dbo.vw_MouldList WHERE MouldID=@MouldID;
    END;');

    EXEC(N'CREATE OR ALTER PROCEDURE dbo.sp_SetPressProductCapability
        @PressEquipmentCode varchar(20), @ProductFamilyID int, @ProductCode varchar(2),
        @IsActive bit, @Remark nvarchar(1000)=NULL, @ChangedBy nvarchar(100)=NULL
    AS
    BEGIN
        SET NOCOUNT ON; SET XACT_ABORT ON;
        DECLARE @OldIsActive bit,@ChangeType varchar(20),@Now datetime2(3)=SYSDATETIME(),
                @ProductFamily varchar(30);
        IF NOT EXISTS (SELECT 1 FROM dbo.EquipmentMaster
            WHERE EquipmentCode=@PressEquipmentCode AND EquipmentType=''PRESS'')
            THROW 50001, ''PressEquipmentCode does not exist or is not PRESS.'', 1;
        SELECT @ProductFamily=ProductFamily FROM dbo.ProductFamilyMaster
        WHERE ProductFamilyID=@ProductFamilyID;
        IF @ProductFamily IS NULL OR NOT EXISTS (SELECT 1 FROM dbo.ProductCodeMaster
            WHERE ProductFamilyID=@ProductFamilyID AND ProductCode=@ProductCode)
            THROW 50002, ''ProductFamilyID / ProductCode does not exist.'', 1;
        BEGIN TRANSACTION;
        SELECT @OldIsActive=IsActive FROM dbo.PressProductCapability WITH (UPDLOCK,HOLDLOCK)
        WHERE PressEquipmentCode=@PressEquipmentCode
          AND ProductFamilyID=@ProductFamilyID AND ProductCode=@ProductCode;
        IF @OldIsActive IS NULL
        BEGIN
            INSERT INTO dbo.PressProductCapability
                (PressEquipmentCode,ProductFamily,ProductFamilyID,ProductCode,IsActive,CreatedAt,UpdatedAt)
            VALUES (@PressEquipmentCode,@ProductFamily,@ProductFamilyID,@ProductCode,@IsActive,@Now,@Now);
            SET @ChangeType=''INITIAL'';
            INSERT INTO dbo.PressProductCapabilityHistory
                (PressEquipmentCode,ProductFamily,ProductFamilyID,ProductCode,IsActive,ChangeType,Remark,ChangedBy,ChangedAt)
            VALUES (@PressEquipmentCode,@ProductFamily,@ProductFamilyID,@ProductCode,@IsActive,@ChangeType,
                    @Remark,COALESCE(@ChangedBy,SUSER_SNAME()),@Now);
        END
        ELSE IF @OldIsActive<>@IsActive
        BEGIN
            UPDATE dbo.PressProductCapability SET IsActive=@IsActive,UpdatedAt=@Now
            WHERE PressEquipmentCode=@PressEquipmentCode
              AND ProductFamilyID=@ProductFamilyID AND ProductCode=@ProductCode;
            SET @ChangeType=CASE WHEN @IsActive=1 THEN ''ENABLE'' ELSE ''DISABLE'' END;
            INSERT INTO dbo.PressProductCapabilityHistory
                (PressEquipmentCode,ProductFamily,ProductFamilyID,ProductCode,IsActive,ChangeType,Remark,ChangedBy,ChangedAt)
            VALUES (@PressEquipmentCode,@ProductFamily,@ProductFamilyID,@ProductCode,@IsActive,@ChangeType,
                    @Remark,COALESCE(@ChangedBy,SUSER_SNAME()),@Now);
        END;
        COMMIT TRANSACTION;
        SELECT p.PressEquipmentCode AS PressCode,em.EquipmentName AS PressName,
            p.ProductFamilyID,pf.ProductFamily,p.ProductCode,pcm.ProductName,pcm.ProductNameTH,
            p.IsActive,p.CreatedAt,p.UpdatedAt
        FROM dbo.PressProductCapability p
        JOIN dbo.EquipmentMaster em ON em.EquipmentCode=p.PressEquipmentCode
        JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamilyID=p.ProductFamilyID
        JOIN dbo.ProductCodeMaster pcm
          ON pcm.ProductFamilyID=p.ProductFamilyID AND pcm.ProductCode=p.ProductCode
        WHERE p.PressEquipmentCode=@PressEquipmentCode
          AND p.ProductFamilyID=@ProductFamilyID AND p.ProductCode=@ProductCode;
    END;');

    EXEC(N'CREATE OR ALTER PROCEDURE dbo.sp_SetPressProductCapabilitySpeed
        @PressEquipmentCode varchar(20), @ProductFamilyID int, @ProductCode varchar(2),
        @StandardSpeed decimal(10,2)
    AS
    BEGIN
        SET NOCOUNT ON; SET XACT_ABORT ON;
        IF @StandardSpeed IS NULL OR @StandardSpeed<=0
            THROW 51001, ''StandardSpeed must be greater than zero.'', 1;
        UPDATE dbo.PressProductCapability SET StandardSpeed=@StandardSpeed,UpdatedAt=SYSDATETIME()
        WHERE PressEquipmentCode=@PressEquipmentCode
          AND ProductFamilyID=@ProductFamilyID AND ProductCode=@ProductCode;
        IF @@ROWCOUNT<>1 THROW 51002, ''Press product capability was not found.'', 1;
    END;');

    EXEC sys.sp_executesql N'
    INSERT INTO #PF_PostMigrationCounts(ObjectName,RowTotal)
    SELECT ''ProductFamilyMaster'',COUNT_BIG(*) FROM dbo.ProductFamilyMaster
    UNION ALL SELECT ''ProductCodeMaster'',COUNT_BIG(*) FROM dbo.ProductCodeMaster
    UNION ALL SELECT ''MaterialProductMap'',COUNT_BIG(*) FROM dbo.MaterialProductMap
    UNION ALL SELECT ''MaterialProductMapHistory'',COUNT_BIG(*) FROM dbo.MaterialProductMapHistory
    UNION ALL SELECT ''MouldMaster'',COUNT_BIG(*) FROM dbo.MouldMaster
    UNION ALL SELECT ''PressProductCapability'',COUNT_BIG(*) FROM dbo.PressProductCapability
    UNION ALL SELECT ''PressProductCapabilityHistory'',COUNT_BIG(*) FROM dbo.PressProductCapabilityHistory
    UNION ALL SELECT ''ProductionLot'',COUNT_BIG(*) FROM dbo.ProductionLot
    UNION ALL SELECT ''Depallet'',COUNT_BIG(*) FROM dbo.Depallet;

    IF EXISTS (SELECT ObjectName,RowTotal FROM #PF_PreMigrationCounts
               EXCEPT SELECT ObjectName,RowTotal FROM #PF_PostMigrationCounts)
       OR EXISTS (SELECT ObjectName,RowTotal FROM #PF_PostMigrationCounts
                  EXCEPT SELECT ObjectName,RowTotal FROM #PF_PreMigrationCounts)
        THROW 52304, ''Table row counts changed during ProductFamilyID migration.'', 1;

    INSERT INTO #PF_PostMigrationSnapshots(ObjectName,ColumnName,RawValue,RawLength,Occurrences)
    SELECT ObjectName,ColumnName,RawValue,RawLength,COUNT_BIG(*)
    FROM (
        SELECT ''ProductFamilyMaster'' AS ObjectName,''ProductFamily'' AS ColumnName,
            CONVERT(varbinary(8000),ProductFamily) AS RawValue,ISNULL(DATALENGTH(ProductFamily),-1) AS RawLength
        FROM dbo.ProductFamilyMaster
        UNION ALL SELECT ''ProductFamilyMaster'',''ProductFamilyTH'',
            CONVERT(varbinary(8000),ProductFamilyTH),ISNULL(DATALENGTH(ProductFamilyTH),-1)
        FROM dbo.ProductFamilyMaster
        UNION ALL SELECT ''ProductCodeMaster'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.ProductCodeMaster
        UNION ALL SELECT ''MaterialProductMap'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.MaterialProductMap
        UNION ALL SELECT ''MaterialProductMapHistory'',''OldProductFamily'',
            CONVERT(varbinary(8000),OldProductFamily),ISNULL(DATALENGTH(OldProductFamily),-1)
        FROM dbo.MaterialProductMapHistory
        UNION ALL SELECT ''MaterialProductMapHistory'',''NewProductFamily'',
            CONVERT(varbinary(8000),NewProductFamily),ISNULL(DATALENGTH(NewProductFamily),-1)
        FROM dbo.MaterialProductMapHistory
        UNION ALL SELECT ''MaterialProductMapHistory'',''OldProductCode'',
            CONVERT(varbinary(8000),OldProductCode),ISNULL(DATALENGTH(OldProductCode),-1)
        FROM dbo.MaterialProductMapHistory
        UNION ALL SELECT ''MaterialProductMapHistory'',''NewProductCode'',
            CONVERT(varbinary(8000),NewProductCode),ISNULL(DATALENGTH(NewProductCode),-1)
        FROM dbo.MaterialProductMapHistory
        UNION ALL SELECT ''MouldMaster'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.MouldMaster
        UNION ALL SELECT ''PressProductCapability'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.PressProductCapability
        UNION ALL SELECT ''PressProductCapabilityHistory'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.PressProductCapabilityHistory
        UNION ALL SELECT ''ProductionLot'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.ProductionLot
        UNION ALL SELECT ''ProductionLot'',''ProductCode'',
            CONVERT(varbinary(8000),ProductCode),ISNULL(DATALENGTH(ProductCode),-1)
        FROM dbo.ProductionLot
        UNION ALL SELECT ''Depallet'',''ProductFamily'',
            CONVERT(varbinary(8000),ProductFamily),ISNULL(DATALENGTH(ProductFamily),-1)
        FROM dbo.Depallet
        UNION ALL SELECT ''Depallet'',''ProductCode'',
            CONVERT(varbinary(8000),ProductCode),ISNULL(DATALENGTH(ProductCode),-1)
        FROM dbo.Depallet
    ) AS snapshot_values
    GROUP BY ObjectName,ColumnName,RawValue,RawLength;

    IF EXISTS (
        SELECT ObjectName,ColumnName,RawValue,RawLength,Occurrences
        FROM #PF_PreMigrationSnapshots
        EXCEPT
        SELECT ObjectName,ColumnName,RawValue,RawLength,Occurrences
        FROM #PF_PostMigrationSnapshots
    ) OR EXISTS (
        SELECT ObjectName,ColumnName,RawValue,RawLength,Occurrences
        FROM #PF_PostMigrationSnapshots
        EXCEPT
        SELECT ObjectName,ColumnName,RawValue,RawLength,Occurrences
        FROM #PF_PreMigrationSnapshots
    )
        THROW 52305, ''A ProductFamily/ProductCode snapshot changed during migration.'', 1;

    IF EXISTS (SELECT 1 FROM dbo.MaterialProductMap
               WHERE (ProductFamily IS NULL AND ProductFamilyID IS NOT NULL)
                  OR (ProductFamily IS NOT NULL AND ProductFamilyID IS NULL))
       OR EXISTS (SELECT 1 FROM dbo.ProductionLot
                  WHERE (ProductFamily IS NULL AND ProductFamilyID IS NOT NULL)
                     OR (ProductFamily IS NOT NULL AND ProductFamilyID IS NULL))
       OR EXISTS (SELECT 1 FROM dbo.MaterialProductMapHistory
                  WHERE (OldProductFamily IS NULL AND OldProductFamilyID IS NOT NULL)
                     OR (OldProductFamily IS NOT NULL AND OldProductFamilyID IS NULL)
                     OR (NewProductFamily IS NULL AND NewProductFamilyID IS NOT NULL)
                     OR (NewProductFamily IS NOT NULL AND NewProductFamilyID IS NULL))
        THROW 52306, ''ProductFamily NULL handling changed during ID backfill.'', 1;
    ';

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
