IF EXISTS (
    SELECT 1 FROM sys.tables
    WHERE object_id = OBJECT_ID('dbo.EquipmentTimeEvent')
)
AND NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('dbo.EquipmentTimeEvent')
      AND name = 'UX_EquipmentTimeEvent_SummaryIdentity'
)
BEGIN
    IF EXISTS (
        SELECT ProductionID, EquipmentCode, TimeType, SourceType
        FROM dbo.EquipmentTimeEvent
        GROUP BY ProductionID, EquipmentCode, TimeType, SourceType
        HAVING COUNT(*) > 1
    )
    BEGIN
        THROW 51000, 'Duplicate EquipmentTimeEvent summary identities exist; unique index was not created.', 1;
    END;

    CREATE UNIQUE INDEX UX_EquipmentTimeEvent_SummaryIdentity
        ON dbo.EquipmentTimeEvent (ProductionID, EquipmentCode, TimeType, SourceType);
END;