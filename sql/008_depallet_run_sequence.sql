SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('dbo.Depallet', 'RunSequence') IS NULL
    ALTER TABLE dbo.Depallet ADD RunSequence int NULL;
GO

IF EXISTS (SELECT 1 FROM dbo.Depallet WHERE RunSequence IS NULL)
BEGIN
    ;WITH NullRuns AS
    (
        SELECT DepalletID,
               DepalletDate,
               ROW_NUMBER() OVER (PARTITION BY DepalletDate ORDER BY DepalletID) AS RowNo
        FROM dbo.Depallet
        WHERE RunSequence IS NULL
    )
    UPDATE d
    SET RunSequence = CONVERT(int, ISNULL(m.MaxSequence, 0) + o.RowNo)
    FROM dbo.Depallet AS d
    INNER JOIN NullRuns AS o ON o.DepalletID = d.DepalletID
    OUTER APPLY
    (
        SELECT MAX(existing.RunSequence) AS MaxSequence
        FROM dbo.Depallet AS existing
        WHERE existing.DepalletDate = o.DepalletDate
          AND existing.RunSequence IS NOT NULL
    ) AS m
    WHERE d.RunSequence IS NULL;
END;
GO

IF EXISTS
(
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.Depallet')
      AND name = 'RunSequence'
      AND is_nullable = 1
)
    ALTER TABLE dbo.Depallet ALTER COLUMN RunSequence int NOT NULL;
GO

IF NOT EXISTS
(
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('dbo.Depallet')
      AND name = 'UX_Depallet_DepalletDate_RunSequence'
)
    CREATE UNIQUE INDEX UX_Depallet_DepalletDate_RunSequence
        ON dbo.Depallet (DepalletDate, RunSequence);
GO

IF NOT EXISTS
(
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.Depallet')
      AND name = 'CK_Depallet_RunSequence_Positive'
)
    ALTER TABLE dbo.Depallet WITH CHECK
        ADD CONSTRAINT CK_Depallet_RunSequence_Positive CHECK (RunSequence > 0);
GO

COMMIT TRANSACTION;
GO
