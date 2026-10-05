-- Rollback also preserves ProductFamilyMaster.ProductFamilyTH as nvarchar(200) NULL.
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF COL_LENGTH('dbo.ProductFamilyMaster','ProductFamilyID') IS NULL
        THROW 52390, 'ProductFamilyID migration is not present.', 1;

    IF EXISTS (
        SELECT 1
        FROM dbo.ProductFamilyMaster pf
        WHERE EXISTS (SELECT 1 FROM dbo.ProductCodeMaster p
                      WHERE p.ProductFamilyID=pf.ProductFamilyID AND
                        (p.ProductFamily COLLATE Latin1_General_100_BIN2<>pf.ProductFamily COLLATE Latin1_General_100_BIN2
                         OR DATALENGTH(p.ProductFamily)<>DATALENGTH(pf.ProductFamily)))
           OR EXISTS (SELECT 1 FROM dbo.MouldMaster m
                      WHERE m.ProductFamilyID=pf.ProductFamilyID AND
                        (m.ProductFamily COLLATE Latin1_General_100_BIN2<>pf.ProductFamily COLLATE Latin1_General_100_BIN2
                         OR DATALENGTH(m.ProductFamily)<>DATALENGTH(pf.ProductFamily)))
           OR EXISTS (SELECT 1 FROM dbo.PressProductCapability c
                      WHERE c.ProductFamilyID=pf.ProductFamilyID AND
                        (c.ProductFamily COLLATE Latin1_General_100_BIN2<>pf.ProductFamily COLLATE Latin1_General_100_BIN2
                         OR DATALENGTH(c.ProductFamily)<>DATALENGTH(pf.ProductFamily)))
           OR EXISTS (SELECT 1 FROM dbo.PressProductCapabilityHistory h
                      WHERE h.ProductFamilyID=pf.ProductFamilyID AND
                        (h.ProductFamily COLLATE Latin1_General_100_BIN2<>pf.ProductFamily COLLATE Latin1_General_100_BIN2
                         OR DATALENGTH(h.ProductFamily)<>DATALENGTH(pf.ProductFamily)))
           OR EXISTS (SELECT 1 FROM dbo.MaterialProductMap m
                      WHERE m.ProductFamilyID=pf.ProductFamilyID AND m.ProductFamily IS NOT NULL AND
                        (m.ProductFamily COLLATE Latin1_General_100_BIN2<>pf.ProductFamily COLLATE Latin1_General_100_BIN2
                         OR DATALENGTH(m.ProductFamily)<>DATALENGTH(pf.ProductFamily)))
           OR EXISTS (SELECT 1 FROM dbo.ProductionLot l
                      WHERE l.ProductFamilyID=pf.ProductFamilyID AND l.ProductFamily IS NOT NULL AND
                        (l.ProductFamily COLLATE Latin1_General_100_BIN2<>pf.ProductFamily COLLATE Latin1_General_100_BIN2
                         OR DATALENGTH(l.ProductFamily)<>DATALENGTH(pf.ProductFamily)))
    )
        THROW 52391, 'Rollback stopped: family snapshots differ from current names; review/restore explicitly first.', 1;

    EXEC(N'CREATE OR ALTER PROCEDURE dbo.sp_Mould_Register
        @MouldName nvarchar(200),@ProductFamily varchar(30),@ProductCode varchar(2),
        @Remark nvarchar(2000)=NULL,@ChangedBy nvarchar(100)=NULL
    AS
    BEGIN
        SET NOCOUNT ON; SET XACT_ABORT ON;
        DECLARE @MouldID bigint,@Seq bigint,@MouldNo varchar(50);
        IF NULLIF(LTRIM(RTRIM(@MouldName)),N'''') IS NULL THROW 50001,''MouldName is required.'',1;
        IF NOT EXISTS (SELECT 1 FROM dbo.ProductCodeMaster
            WHERE ProductFamily=@ProductFamily AND ProductCode=@ProductCode)
            THROW 50002,''Invalid ProductFamily / ProductCode.'',1;
        BEGIN TRANSACTION;
        SET @Seq=NEXT VALUE FOR dbo.Seq_MouldNo;
        SET @MouldNo=''M''+RIGHT(''000000''+CONVERT(varchar(20),@Seq),6);
        INSERT INTO dbo.MouldMaster
            (MouldNo,MouldName,ProductFamily,ProductCode,Status,CurrentReconditionNo,Remark)
        VALUES (@MouldNo,@MouldName,@ProductFamily,@ProductCode,''ACTIVE'',0,@Remark);
        SET @MouldID=SCOPE_IDENTITY();
        INSERT INTO dbo.MouldStatusHistory
            (MouldID,FromStatus,ToStatus,ChangeType,Remark,ChangedBy)
        VALUES (@MouldID,NULL,''ACTIVE'',''REGISTER'',N''New mould registered'',@ChangedBy);
        COMMIT TRANSACTION;
        SELECT * FROM dbo.vw_MouldList WHERE MouldID=@MouldID;
    END;');

    EXEC(N'CREATE OR ALTER PROCEDURE dbo.sp_SetPressProductCapability
        @PressEquipmentCode varchar(20),@ProductFamily varchar(30),@ProductCode varchar(2),
        @IsActive bit,@Remark nvarchar(1000)=NULL,@ChangedBy nvarchar(100)=NULL
    AS
    BEGIN
        SET NOCOUNT ON; SET XACT_ABORT ON;
        DECLARE @OldIsActive bit,@ChangeType varchar(20),@Now datetime2(3)=SYSDATETIME();
        IF NOT EXISTS (SELECT 1 FROM dbo.EquipmentMaster
            WHERE EquipmentCode=@PressEquipmentCode AND EquipmentType=''PRESS'')
            THROW 50001,''PressEquipmentCode does not exist or is not PRESS.'',1;
        IF NOT EXISTS (SELECT 1 FROM dbo.ProductCodeMaster
            WHERE ProductFamily=@ProductFamily AND ProductCode=@ProductCode)
            THROW 50002,''ProductFamily / ProductCode does not exist.'',1;
        BEGIN TRANSACTION;
        SELECT @OldIsActive=IsActive FROM dbo.PressProductCapability WITH (UPDLOCK,HOLDLOCK)
        WHERE PressEquipmentCode=@PressEquipmentCode AND ProductFamily=@ProductFamily
          AND ProductCode=@ProductCode;
        IF @OldIsActive IS NULL
        BEGIN
            INSERT INTO dbo.PressProductCapability
                (PressEquipmentCode,ProductFamily,ProductCode,IsActive,CreatedAt,UpdatedAt)
            VALUES (@PressEquipmentCode,@ProductFamily,@ProductCode,@IsActive,@Now,@Now);
            SET @ChangeType=''INITIAL'';
            INSERT INTO dbo.PressProductCapabilityHistory
                (PressEquipmentCode,ProductFamily,ProductCode,IsActive,ChangeType,Remark,ChangedBy,ChangedAt)
            VALUES (@PressEquipmentCode,@ProductFamily,@ProductCode,@IsActive,@ChangeType,
                    @Remark,COALESCE(@ChangedBy,SUSER_SNAME()),@Now);
        END
        ELSE IF @OldIsActive<>@IsActive
        BEGIN
            UPDATE dbo.PressProductCapability SET IsActive=@IsActive,UpdatedAt=@Now
            WHERE PressEquipmentCode=@PressEquipmentCode AND ProductFamily=@ProductFamily
              AND ProductCode=@ProductCode;
            SET @ChangeType=CASE WHEN @IsActive=1 THEN ''ENABLE'' ELSE ''DISABLE'' END;
            INSERT INTO dbo.PressProductCapabilityHistory
                (PressEquipmentCode,ProductFamily,ProductCode,IsActive,ChangeType,Remark,ChangedBy,ChangedAt)
            VALUES (@PressEquipmentCode,@ProductFamily,@ProductCode,@IsActive,@ChangeType,
                    @Remark,COALESCE(@ChangedBy,SUSER_SNAME()),@Now);
        END;
        COMMIT TRANSACTION;
        SELECT p.PressEquipmentCode AS PressCode,em.EquipmentName AS PressName,
            p.ProductFamily,p.ProductCode,pcm.ProductName,pcm.ProductNameTH,
            p.IsActive,p.CreatedAt,p.UpdatedAt
        FROM dbo.PressProductCapability p
        JOIN dbo.EquipmentMaster em ON em.EquipmentCode=p.PressEquipmentCode
        JOIN dbo.ProductCodeMaster pcm
          ON pcm.ProductFamily=p.ProductFamily AND pcm.ProductCode=p.ProductCode
        WHERE p.PressEquipmentCode=@PressEquipmentCode
          AND p.ProductFamily=@ProductFamily AND p.ProductCode=@ProductCode;
    END;');

    EXEC(N'CREATE OR ALTER PROCEDURE dbo.sp_SetPressProductCapabilitySpeed
        @PressEquipmentCode varchar(20),@ProductFamily varchar(30),@ProductCode varchar(2),
        @StandardSpeed decimal(10,2)
    AS
    BEGIN
        SET NOCOUNT ON; SET XACT_ABORT ON;
        IF @StandardSpeed IS NULL OR @StandardSpeed<=0
            THROW 51001,''StandardSpeed must be greater than zero.'',1;
        UPDATE dbo.PressProductCapability SET StandardSpeed=@StandardSpeed,UpdatedAt=SYSDATETIME()
        WHERE PressEquipmentCode=@PressEquipmentCode AND ProductFamily=@ProductFamily
          AND ProductCode=@ProductCode;
        IF @@ROWCOUNT<>1 THROW 51002,''Press product capability was not found.'',1;
    END;');

    ALTER TABLE dbo.ProductionLot DROP CONSTRAINT FK_ProductionLot_FamilyIDCode;
    ALTER TABLE dbo.PressProductCapabilityHistory DROP CONSTRAINT FK_PressProductCapabilityHistory_ProductID;
    ALTER TABLE dbo.PressProductCapability DROP CONSTRAINT FK_PressProductCapability_ProductID;
    ALTER TABLE dbo.MouldMaster DROP CONSTRAINT FK_MouldMaster_ProductID;
    ALTER TABLE dbo.MaterialProductMap DROP CONSTRAINT FK_MaterialProductMap_FamilyIDCode;
    ALTER TABLE dbo.ProductCodeMaster DROP CONSTRAINT FK_ProductCodeMaster_FamilyID;

    ALTER TABLE dbo.ProductFamilyMaster DROP CONSTRAINT CK_ProductFamilyMaster_LotPrefixLetter;
    ALTER TABLE dbo.ProductFamilyMaster DROP CONSTRAINT UQ_ProductFamilyMaster_ProductFamily;
    ALTER TABLE dbo.ProductFamilyMaster DROP CONSTRAINT PK_ProductFamilyMaster;
    ALTER TABLE dbo.ProductFamilyMaster ADD CONSTRAINT PK_ProductFamilyMaster
        PRIMARY KEY CLUSTERED(ProductFamily);
    ALTER TABLE dbo.ProductFamilyMaster ADD CONSTRAINT CK_ProductFamilyMaster_Prefix
        CHECK (((ProductFamily='Oriental' OR ProductFamily='NeuFit / NeuStile') AND LotPrefixLetter='B')
            OR ((ProductFamily='Prestige Common' OR ProductFamily='Special Ridge') AND LotPrefixLetter='I'));

    ALTER TABLE dbo.ProductCodeMaster DROP CONSTRAINT PK_ProductCodeMaster;
    ALTER TABLE dbo.ProductCodeMaster ADD CONSTRAINT PK_ProductCodeMaster
        PRIMARY KEY CLUSTERED(ProductFamily,ProductCode);
    ALTER TABLE dbo.ProductCodeMaster ADD CONSTRAINT FK_ProductCodeMaster_Family
        FOREIGN KEY(ProductFamily) REFERENCES dbo.ProductFamilyMaster(ProductFamily);
    ALTER TABLE dbo.MaterialProductMap ADD CONSTRAINT FK_MaterialProductMap_FamilyCode
        FOREIGN KEY(ProductFamily,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode);
    ALTER TABLE dbo.MouldMaster ADD CONSTRAINT FK_MouldMaster_Product
        FOREIGN KEY(ProductFamily,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode);
    ALTER TABLE dbo.PressProductCapability DROP CONSTRAINT PK_PressProductCapability;
    ALTER TABLE dbo.PressProductCapability ADD CONSTRAINT PK_PressProductCapability
        PRIMARY KEY CLUSTERED(PressEquipmentCode,ProductFamily,ProductCode);
    ALTER TABLE dbo.PressProductCapability ADD CONSTRAINT FK_PressProductCapability_Product
        FOREIGN KEY(ProductFamily,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode);
    ALTER TABLE dbo.PressProductCapabilityHistory ADD CONSTRAINT FK_PressProductCapabilityHistory_Product
        FOREIGN KEY(ProductFamily,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode);
    ALTER TABLE dbo.ProductionLot ADD CONSTRAINT FK_ProductionLot_FamilyCode
        FOREIGN KEY(ProductFamily,ProductCode)
        REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode);

    DROP INDEX IX_PressProductCapability_Product ON dbo.PressProductCapability;
    CREATE INDEX IX_PressProductCapability_Product
        ON dbo.PressProductCapability(ProductFamily,ProductCode,IsActive)
        INCLUDE(PressEquipmentCode);
    DROP INDEX IX_PressProductCapabilityHistory_PressProduct ON dbo.PressProductCapabilityHistory;
    CREATE INDEX IX_PressProductCapabilityHistory_PressProduct
        ON dbo.PressProductCapabilityHistory(PressEquipmentCode,ProductFamily,ProductCode,ChangedAt);

    DROP INDEX UX_ProductionLot_FamilyLotNo ON dbo.ProductionLot;
    DROP INDEX UX_ProductionLot_FamilySequence ON dbo.ProductionLot;
    DROP INDEX UX_ProductionLot_LegacyLotNo ON dbo.ProductionLot;
    DROP INDEX UX_ProductionLot_LegacySequence ON dbo.ProductionLot;
    CREATE UNIQUE INDEX UX_ProductionLot_FamilyLotNo
        ON dbo.ProductionLot(ProductFamily,LotNo)
        WHERE IsActive=1 AND ProductFamily IS NOT NULL;
    CREATE UNIQUE INDEX UX_ProductionLot_FamilySequence
        ON dbo.ProductionLot(ProductFamily,ProductCode,SequenceMonth,RunningNo)
        WHERE IsActive=1 AND ProductFamily IS NOT NULL;
    CREATE UNIQUE INDEX UX_ProductionLot_LegacyLotNo
        ON dbo.ProductionLot(LotNo)
        WHERE IsActive=1 AND ProductFamily IS NULL;
    CREATE UNIQUE INDEX UX_ProductionLot_LegacySequence
        ON dbo.ProductionLot(LotPrefix,RunningNo)
        WHERE IsActive=1 AND ProductFamily IS NULL;

    EXEC(N'CREATE OR ALTER VIEW dbo.vw_MouldList AS
        SELECT m.MouldID,m.MouldNo,m.MouldName,m.ProductFamily,m.ProductCode,
            pcm.ProductName,m.Status,m.CurrentReconditionNo,l.CurrentAge,l.LifetimeAge,
            l.UsageRecordCount,l.LastUsageDateTime,m.Remark,m.CreatedAt,m.UpdatedAt
        FROM dbo.MouldMaster m
        LEFT JOIN dbo.ProductCodeMaster pcm
          ON pcm.ProductFamily=m.ProductFamily AND pcm.ProductCode=m.ProductCode
        LEFT JOIN dbo.vw_MouldLifeSummary l ON l.MouldID=m.MouldID;');
    EXEC(N'CREATE OR ALTER VIEW dbo.vw_PressMcCapabilityMatrix AS
        SELECT p.PressCode,p.PressName,p.CurrentLine,p.CurrentLineName,
            pc.ProductFamily,pc.ProductCode,pc.ProductName,pc.ProductNameTH,
            CAST(CASE WHEN cap.IsActive=1 THEN 1 ELSE 0 END AS bit) AS CanProduce,cap.StandardSpeed
        FROM dbo.vw_PressMcPressList p CROSS JOIN dbo.ProductCodeMaster pc
        LEFT JOIN dbo.PressProductCapability cap
          ON cap.PressEquipmentCode=p.PressCode AND cap.ProductFamily=pc.ProductFamily
         AND cap.ProductCode=pc.ProductCode WHERE pc.IsActive=1;');

    ALTER TABLE dbo.ProductFamilyMaster DROP COLUMN ProductFamilyID;
    ALTER TABLE dbo.ProductCodeMaster DROP COLUMN ProductFamilyID;
    ALTER TABLE dbo.MaterialProductMap DROP COLUMN ProductFamilyID;
    ALTER TABLE dbo.MaterialProductMapHistory DROP COLUMN OldProductFamilyID,NewProductFamilyID;
    ALTER TABLE dbo.MouldMaster DROP COLUMN ProductFamilyID;
    ALTER TABLE dbo.PressProductCapability DROP COLUMN ProductFamilyID;
    ALTER TABLE dbo.PressProductCapabilityHistory DROP COLUMN ProductFamilyID;
    ALTER TABLE dbo.ProductionLot DROP COLUMN ProductFamilyID;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE()<>0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
