IF COL_LENGTH('dbo.Depallet', 'StartDateTime') IS NULL
    ALTER TABLE dbo.Depallet ADD StartDateTime datetime2(3) NULL;
GO

IF COL_LENGTH('dbo.Depallet', 'EndDateTime') IS NULL
    ALTER TABLE dbo.Depallet ADD EndDateTime datetime2(3) NULL;
GO
