SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF COL_LENGTH('dbo.ProductionLot','IsActive') IS NULL
    ALTER TABLE dbo.ProductionLot ADD IsActive bit NOT NULL CONSTRAINT DF_ProductionLot_IsActive DEFAULT(1);
-- Dynamic batches allow an added column to be referenced on the first run.
EXEC(N'
IF EXISTS(SELECT 1 FROM dbo.ProductionLot WHERE IsActive=1 GROUP BY ProdDate,PlanName HAVING COUNT(*)>1)
    THROW 51000, ''Existing active lots share a plan/date. Resolve before migration.'', 1;
IF EXISTS(SELECT 1 FROM dbo.ProductionLot WHERE IsActive=1 GROUP BY LotPrefix,RunningNo HAVING COUNT(*)>1)
    THROW 51000, ''Existing active sequence numbers overlap.'', 1;
IF EXISTS(SELECT 1 FROM dbo.ProductionLot WHERE IsActive=1 GROUP BY LotPrefix HAVING MIN(RunningNo)<>1 OR MAX(RunningNo)<>COUNT(*))
    THROW 51000, ''Existing active sequences have gaps. Resolve before migration.'', 1;
');
IF OBJECT_ID('dbo.ProductionLotHistory','U') IS NULL
CREATE TABLE dbo.ProductionLotHistory (
    HistoryID bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
    ProductionID bigint NOT NULL REFERENCES dbo.ProductionLot(ProductionID),
    OldLotNo varchar(30) NULL, NewLotNo varchar(30) NULL,
    OldPlanName varchar(50) NULL, NewPlanName varchar(50) NULL,
    ChangeType varchar(20) NOT NULL,
    ChangedAt datetime2(3) NOT NULL DEFAULT SYSDATETIME()
);
IF EXISTS(SELECT 1 FROM sys.key_constraints WHERE parent_object_id=OBJECT_ID('dbo.ProductionLot') AND name='UQ_ProductionLot_LotNo')
    ALTER TABLE dbo.ProductionLot DROP CONSTRAINT UQ_ProductionLot_LotNo;
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_ActiveLotNo')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_ActiveLotNo ON dbo.ProductionLot(LotNo) WHERE IsActive=1');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_ActivePlan')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_ActivePlan ON dbo.ProductionLot(ProdDate,PlanName) WHERE IsActive=1');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='UX_ProductionLot_ActiveSequence')
    EXEC(N'CREATE UNIQUE INDEX UX_ProductionLot_ActiveSequence ON dbo.ProductionLot(LotPrefix,RunningNo) WHERE IsActive=1');
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.ProductionLot') AND name='IX_ProductionLot_ActiveUpdated')
    EXEC(N'CREATE INDEX IX_ProductionLot_ActiveUpdated ON dbo.ProductionLot(UpdatedAt DESC,ProductionID DESC) WHERE IsActive=1');
COMMIT TRANSACTION;

