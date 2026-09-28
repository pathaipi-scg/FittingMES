SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID('dbo.ProductionPISLog', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ProductionPISLog
    (
        PISLogID bigint IDENTITY(1,1) NOT NULL,
        ProductionID bigint NOT NULL,
        LotNo varchar(30) NOT NULL,
        ProductionDate date NOT NULL,
        ShiftCode varchar(10) NULL,
        PlantCode varchar(30) NULL,
        MachineCode varchar(30) NULL,
        RequestGroupID uniqueidentifier NOT NULL,
        RequestJSON nvarchar(max) NULL,
        HTTPStatus int NULL,
        ResponseText nvarchar(max) NULL,
        Outcome varchar(20) NOT NULL,
        ErrorMessage nvarchar(4000) NULL,
        AttemptedAt datetime2(0) NOT NULL,
        CreatedAt datetime2(0) NOT NULL
            CONSTRAINT DF_ProductionPISLog_CreatedAt DEFAULT SYSDATETIME(),
        CONSTRAINT PK_ProductionPISLog PRIMARY KEY CLUSTERED (PISLogID),
        CONSTRAINT CK_ProductionPISLog_Outcome
            CHECK (Outcome IN ('SUCCESS', 'FAILED', 'UNKNOWN')),
        CONSTRAINT FK_ProductionPISLog_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID)
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.ProductionPISLog')
      AND name='IX_ProductionPISLog_ProductionAttemptedAt'
)
    CREATE INDEX IX_ProductionPISLog_ProductionAttemptedAt
        ON dbo.ProductionPISLog(ProductionID, AttemptedAt DESC);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.ProductionPISLog')
      AND name='IX_ProductionPISLog_RequestGroup'
)
    CREATE INDEX IX_ProductionPISLog_RequestGroup
        ON dbo.ProductionPISLog(ProductionDate, ShiftCode, PlantCode, MachineCode, RequestGroupID);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.ProductionPISLog')
      AND name='UX_ProductionPISLog_ProductionSuccess'
)
    CREATE UNIQUE INDEX UX_ProductionPISLog_ProductionSuccess
        ON dbo.ProductionPISLog(ProductionID)
        WHERE Outcome='SUCCESS';

COMMIT TRANSACTION;
