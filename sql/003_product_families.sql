SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID('dbo.ProductFamilyMaster','U') IS NULL
BEGIN
    CREATE TABLE dbo.ProductFamilyMaster (
        ProductFamily varchar(30) NOT NULL CONSTRAINT PK_ProductFamilyMaster PRIMARY KEY,
        LotPrefixLetter char(1) NOT NULL,
        CONSTRAINT CK_ProductFamilyMaster_Prefix CHECK (
          (ProductFamily IN ('NeuFit / NeuStile','Oriental') AND LotPrefixLetter='B') OR
          (ProductFamily IN ('Special Ridge','Prestige Common') AND LotPrefixLetter='I'))
    );
    INSERT INTO dbo.ProductFamilyMaster VALUES
      ('NeuFit / NeuStile','B'),('Oriental','B'),('Special Ridge','I'),('Prestige Common','I');
END;
IF COL_LENGTH('dbo.ProductCodeMaster','ProductFamily') IS NULL
BEGIN
    -- These are explicit master categories, NOT inferred material/lot assignments.
    IF EXISTS(SELECT 1 FROM dbo.ProductCodeMaster WHERE ProductGroup NOT IN
      (N'NeuFit',N'NeuStile',N'NeuFit / NeuStile',N'Oriental',N'Special Ridge',N'Prestige Common'))
        THROW 51000, 'Unrecognized product master group; migration requires explicit reference.', 1;
    ALTER TABLE dbo.ProductCodeMaster ADD ProductFamily varchar(30) NULL;
    EXEC(N'UPDATE dbo.ProductCodeMaster SET ProductFamily=
      CASE WHEN ProductGroup IN (N''NeuFit'',N''NeuStile'',N''NeuFit / NeuStile'')
           THEN ''NeuFit / NeuStile'' ELSE CONVERT(varchar(30),ProductGroup) END');
END;
IF COL_LENGTH('dbo.MaterialProductMap','ProductFamily') IS NULL
    ALTER TABLE dbo.MaterialProductMap ADD ProductFamily varchar(30) NULL;
IF COL_LENGTH('dbo.ProductionLot','ProductFamily') IS NULL
    ALTER TABLE dbo.ProductionLot ADD ProductFamily varchar(30) NULL;
IF COL_LENGTH('dbo.ProductionLot','SequenceMonth') IS NULL
    ALTER TABLE dbo.ProductionLot ADD SequenceMonth AS
      (DATEFROMPARTS(YEAR(ProdDate),MONTH(ProdDate),1)) PERSISTED;
-- Deliberately NO backfill of MaterialProductMap or ProductionLot family.
IF OBJECT_ID('dbo.FK_MaterialProductMap_ProductCode','F') IS NOT NULL
    ALTER TABLE dbo.MaterialProductMap DROP CONSTRAINT FK_MaterialProductMap_ProductCode;
IF OBJECT_ID('dbo.FK_ProductionLot_ProductCode','F') IS NOT NULL
    ALTER TABLE dbo.ProductionLot DROP CONSTRAINT FK_ProductionLot_ProductCode;
IF NOT EXISTS(SELECT 1 FROM sys.index_columns ic JOIN sys.columns c
  ON c.object_id=ic.object_id AND c.column_id=ic.column_id JOIN sys.indexes i
  ON i.object_id=ic.object_id AND i.index_id=ic.index_id
  WHERE i.object_id=OBJECT_ID('dbo.ProductCodeMaster') AND i.is_primary_key=1 AND c.name='ProductFamily')
BEGIN
    ALTER TABLE dbo.ProductCodeMaster DROP CONSTRAINT PK_ProductCodeMaster;
    EXEC(N'ALTER TABLE dbo.ProductCodeMaster ALTER COLUMN ProductFamily varchar(30) NOT NULL');
    EXEC(N'ALTER TABLE dbo.ProductCodeMaster ADD CONSTRAINT PK_ProductCodeMaster PRIMARY KEY (ProductFamily,ProductCode)');
END;
IF OBJECT_ID('dbo.FK_ProductCodeMaster_Family','F') IS NULL
    EXEC(N'ALTER TABLE dbo.ProductCodeMaster ADD CONSTRAINT FK_ProductCodeMaster_Family
      FOREIGN KEY(ProductFamily) REFERENCES dbo.ProductFamilyMaster(ProductFamily)');
IF OBJECT_ID('dbo.FK_MaterialProductMap_FamilyCode','F') IS NULL
    EXEC(N'ALTER TABLE dbo.MaterialProductMap ADD CONSTRAINT FK_MaterialProductMap_FamilyCode
      FOREIGN KEY(ProductFamily,ProductCode) REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode)');
IF OBJECT_ID('dbo.FK_ProductionLot_FamilyCode','F') IS NULL
    EXEC(N'ALTER TABLE dbo.ProductionLot ADD CONSTRAINT FK_ProductionLot_FamilyCode
      FOREIGN KEY(ProductFamily,ProductCode) REFERENCES dbo.ProductCodeMaster(ProductFamily,ProductCode)');
IF EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_ActiveSequence')
    DROP INDEX UX_ProductionLot_ActiveSequence ON dbo.ProductionLot;
IF EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_ActiveLotNo')
    DROP INDEX UX_ProductionLot_ActiveLotNo ON dbo.ProductionLot;
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_FamilySequence')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_FamilySequence ON dbo.ProductionLot
      (ProductFamily,ProductCode,SequenceMonth,RunningNo) WHERE IsActive=1 AND ProductFamily IS NOT NULL');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_FamilyLotNo')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_FamilyLotNo ON dbo.ProductionLot
      (ProductFamily,LotNo) WHERE IsActive=1 AND ProductFamily IS NOT NULL');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_LegacySequence')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_LegacySequence ON dbo.ProductionLot
      (LotPrefix,RunningNo) WHERE IsActive=1 AND ProductFamily IS NULL');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_LegacyLotNo')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_LegacyLotNo ON dbo.ProductionLot
      (LotNo) WHERE IsActive=1 AND ProductFamily IS NULL');
COMMIT TRANSACTION;
-- Report unresolved records without assigning a family.
EXEC(N'SELECT MaterialPrefix,ProductCode FROM dbo.MaterialProductMap WHERE ProductFamily IS NULL');
EXEC(N'SELECT ProductionID,LotNo,ProductCode FROM dbo.ProductionLot WHERE ProductFamily IS NULL');
