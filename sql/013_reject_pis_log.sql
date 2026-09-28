IF OBJECT_ID(N'dbo.RejectPISLog', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.RejectPISLog
    (
        RejectPISLogID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_RejectPISLog PRIMARY KEY,
        ProductionID bigint NOT NULL,
        LotNo varchar(100) NULL,
        ProductionDate date NOT NULL,
        RequestGroupID uniqueidentifier NOT NULL,
        FromOutputDetailID varchar(100) NULL,
        RequestJSON nvarchar(max) NULL,
        HTTPStatus int NULL,
        ResponseText nvarchar(max) NULL,
        Outcome varchar(20) NOT NULL
            CONSTRAINT CK_RejectPISLog_Outcome CHECK (Outcome IN ('SUCCESS','FAILED','UNKNOWN')),
        ErrorMessage nvarchar(1000) NULL,
        AttemptedAt datetime2(3) NOT NULL,
        CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_RejectPISLog_CreatedAt DEFAULT SYSUTCDATETIME()
    );
    CREATE INDEX IX_RejectPISLog_Production
        ON dbo.RejectPISLog (ProductionID, AttemptedAt DESC, RejectPISLogID DESC);
    CREATE INDEX IX_RejectPISLog_RequestGroup
        ON dbo.RejectPISLog (RequestGroupID);
END
GO
