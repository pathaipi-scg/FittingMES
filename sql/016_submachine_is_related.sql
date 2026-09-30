SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('dbo.Fitting_SubMachine', 'IsRelated') IS NULL
BEGIN
    ALTER TABLE dbo.Fitting_SubMachine
        ADD IsRelated bit NOT NULL
            CONSTRAINT DF_Fitting_SubMachine_IsRelated DEFAULT (0);
END;
ELSE IF EXISTS
(
    SELECT 1
    FROM sys.columns c
    JOIN sys.tables t ON t.object_id = c.object_id
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    WHERE s.name = 'dbo'
      AND t.name = 'Fitting_SubMachine'
      AND c.name = 'IsRelated'
      AND (ty.name <> 'bit' OR c.is_nullable <> 0)
)
BEGIN
    THROW 51000, 'dbo.Fitting_SubMachine.IsRelated has an unexpected definition.', 1;
END;

EXEC sys.sp_executesql N'
    UPDATE dbo.Fitting_SubMachine
    SET IsRelated = 1
    WHERE SubMcId BETWEEN 20 AND 26
      AND IsRelated <> 1;';

COMMIT TRANSACTION;
GO