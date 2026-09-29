IF COL_LENGTH('dbo.PressProduction', 'ReleasedAt') IS NULL
BEGIN
    ALTER TABLE dbo.PressProduction
        ADD ReleasedAt datetime2(3) NULL;
END;
GO

IF COL_LENGTH('dbo.PressProduction', 'ReleasedBy') IS NULL
BEGIN
    ALTER TABLE dbo.PressProduction
        ADD ReleasedBy nvarchar(200) NULL;
END;
GO