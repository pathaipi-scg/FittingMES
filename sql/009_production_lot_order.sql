SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF COL_LENGTH('dbo.ProductionLot','LotSequence') IS NULL
    ALTER TABLE dbo.ProductionLot ADD LotSequence int NULL;
EXEC(N'
WITH OrderedLots AS (
    SELECT ProductionID, ROW_NUMBER() OVER (
        PARTITION BY ProdDate ORDER BY UpdatedAt DESC, ProductionID DESC
    ) AS LotSequence
    FROM dbo.ProductionLot
)
UPDATE p SET LotSequence=o.LotSequence
FROM dbo.ProductionLot p JOIN OrderedLots o ON o.ProductionID=p.ProductionID
WHERE p.LotSequence IS NULL;
');
EXEC(N'
IF EXISTS (SELECT 1 FROM dbo.ProductionLot WHERE LotSequence IS NULL)
    THROW 51000, ''ProductionLot LotSequence backfill left NULL rows.'', 1;
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(''dbo.ProductionLot'')
           AND name=''LotSequence'' AND is_nullable=1)
    ALTER TABLE dbo.ProductionLot ALTER COLUMN LotSequence int NOT NULL;
');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='IX_ProductionLot_ActiveDateSequence')
    EXEC(N'CREATE INDEX IX_ProductionLot_ActiveDateSequence ON dbo.ProductionLot(ProdDate,LotSequence,ProductionID) WHERE IsActive=1');
COMMIT TRANSACTION;