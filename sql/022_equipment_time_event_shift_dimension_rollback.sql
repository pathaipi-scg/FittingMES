SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('dbo.EquipmentTimeEvent', 'ShiftID') IS NULL
BEGIN
    COMMIT TRANSACTION;
    RETURN;
END;

IF EXISTS (
    SELECT 1
    FROM dbo.EquipmentTimeEvent
    WHERE SourceType='MANUAL' AND ShiftID=2
)
    THROW 51001, 'Rollback refused: MANUAL Shift 2 rows exist.', 1;

IF EXISTS (
    SELECT ProductionID, EquipmentCode, TimeType, SourceType
    FROM dbo.EquipmentTimeEvent
    GROUP BY ProductionID, EquipmentCode, TimeType, SourceType
    HAVING COUNT(*) > 1
)
    THROW 51001, 'Rollback refused: legacy four-column identities are no longer unique.', 1;

IF EXISTS (
    SELECT 1
    FROM sys.check_constraints
    WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
      AND name='CK_EquipmentTimeEvent_ManualShift'
)
    ALTER TABLE dbo.EquipmentTimeEvent
        DROP CONSTRAINT CK_EquipmentTimeEvent_ManualShift;

IF EXISTS (
    SELECT 1
    FROM sys.check_constraints
    WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
      AND name='CK_EquipmentTimeEvent_ShiftID'
)
    ALTER TABLE dbo.EquipmentTimeEvent
        DROP CONSTRAINT CK_EquipmentTimeEvent_ShiftID;

IF EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
      AND name='UX_EquipmentTimeEvent_ManualShiftIdentity'
)
    DROP INDEX UX_EquipmentTimeEvent_ManualShiftIdentity
        ON dbo.EquipmentTimeEvent;

UPDATE dbo.EquipmentTimeEvent
    SET ShiftID=NULL
    WHERE SourceType='MANUAL';

ALTER TABLE dbo.EquipmentTimeEvent
    DROP COLUMN ShiftID;

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
      AND name='UX_EquipmentTimeEvent_SummaryIdentity'
)
    CREATE UNIQUE INDEX UX_EquipmentTimeEvent_SummaryIdentity
        ON dbo.EquipmentTimeEvent
           (ProductionID, EquipmentCode, TimeType, SourceType);

COMMIT TRANSACTION;
GO
