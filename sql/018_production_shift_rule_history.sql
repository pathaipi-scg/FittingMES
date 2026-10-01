SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID('dbo.ProductionShiftRuleHistory','U') IS NULL
BEGIN
    CREATE TABLE dbo.ProductionShiftRuleHistory (
        RuleID bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
        EffectiveFromDate date NOT NULL,
        ShiftID int NOT NULL,
        StartTime time(0) NOT NULL,
        CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_ProductionShiftRuleHistory_CreatedAt DEFAULT SYSDATETIME(),
        Remark nvarchar(500) NULL,
        CONSTRAINT CK_ProductionShiftRuleHistory_ShiftID CHECK (ShiftID > 0)
    );
END;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.ProductionShiftRuleHistory')
      AND name='UX_ProductionShiftRuleHistory_EffectiveShift'
)
    CREATE UNIQUE INDEX UX_ProductionShiftRuleHistory_EffectiveShift
        ON dbo.ProductionShiftRuleHistory(EffectiveFromDate, ShiftID);

IF NOT EXISTS (
    SELECT 1 FROM dbo.ProductionShiftRuleHistory
    WHERE EffectiveFromDate='2026-01-01' AND ShiftID=1
)
    INSERT INTO dbo.ProductionShiftRuleHistory
        (EffectiveFromDate, ShiftID, StartTime, Remark)
    VALUES ('2026-01-01', 1, '06:00:00', N'Initial factory shift schedule');

IF NOT EXISTS (
    SELECT 1 FROM dbo.ProductionShiftRuleHistory
    WHERE EffectiveFromDate='2026-01-01' AND ShiftID=2
)
    INSERT INTO dbo.ProductionShiftRuleHistory
        (EffectiveFromDate, ShiftID, StartTime, Remark)
    VALUES ('2026-01-01', 2, '20:00:00', N'Initial factory shift schedule');

COMMIT TRANSACTION;