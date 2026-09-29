SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID('dbo.MaterialProductMapHistory','U') IS NULL
BEGIN
    CREATE TABLE dbo.MaterialProductMapHistory (
        MaterialProductMapHistoryID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_MaterialProductMapHistory PRIMARY KEY,
        MaterialPrefix varchar(20) NOT NULL,
        OldProductFamily varchar(30) NULL,
        OldProductCode varchar(2) NULL,
        NewProductFamily varchar(30) NULL,
        NewProductCode varchar(2) NULL,
        ChangedAt datetime2(6) NOT NULL
            CONSTRAINT DF_MaterialProductMapHistory_ChangedAt DEFAULT SYSDATETIME()
    );
END;
COMMIT TRANSACTION;