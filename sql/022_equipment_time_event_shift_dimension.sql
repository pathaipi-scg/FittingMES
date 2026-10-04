SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID('dbo.EquipmentTimeEvent', 'U') IS NULL
        THROW 51000, 'EquipmentTimeEvent table does not exist.', 1;

    /* Validate the existing legacy identity without binding to ShiftID. */
    IF EXISTS (
        SELECT 1
        FROM sys.indexes AS i
        WHERE i.object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND i.name='UX_EquipmentTimeEvent_SummaryIdentity'
          AND (
              i.is_unique<>1
              OR i.filter_definition IS NOT NULL
              OR (SELECT COUNT(*)
                  FROM sys.index_columns AS ic
                  WHERE ic.object_id=i.object_id
                    AND ic.index_id=i.index_id
                    AND ic.is_included_column=0)<>4
              OR EXISTS (
                  SELECT 1
                  FROM sys.index_columns AS ic
                  WHERE ic.object_id=i.object_id
                    AND ic.index_id=i.index_id
                    AND ic.is_included_column=1
              )
              OR EXISTS (
                  SELECT 1
                  FROM sys.index_columns AS ic
                  JOIN sys.columns AS c
                    ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                  WHERE ic.object_id=i.object_id
                    AND ic.index_id=i.index_id
                    AND ic.is_included_column=0
                    AND (
                        (ic.key_ordinal=1 AND c.name<>'ProductionID')
                        OR (ic.key_ordinal=2 AND c.name<>'EquipmentCode')
                        OR (ic.key_ordinal=3 AND c.name<>'TimeType')
                        OR (ic.key_ordinal=4 AND c.name<>'SourceType')
                        OR ic.key_ordinal NOT BETWEEN 1 AND 4
                    )
              )
          )
    )
        THROW 51000, 'Existing legacy EquipmentTimeEvent index has an unexpected definition.', 1;

    /* Validate an already-created Shift-aware identity from catalog metadata. */
    IF EXISTS (
        SELECT 1
        FROM sys.indexes AS i
        WHERE i.object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND i.name='UX_EquipmentTimeEvent_ManualShiftIdentity'
          AND (
              i.is_unique<>1
              OR i.filter_definition IS NULL
              OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(i.filter_definition,
                    ' ', ''), '[', ''), ']', ''), '(', '')) = ''
              OR LOWER(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(i.filter_definition,
                    ' ', ''), '[', ''), ']', ''), '(', ''), ')', ''))
                    <> 'sourcetype=' + CHAR(39) + 'manual' + CHAR(39)
              OR (SELECT COUNT(*)
                  FROM sys.index_columns AS ic
                  WHERE ic.object_id=i.object_id
                    AND ic.index_id=i.index_id
                    AND ic.is_included_column=0)<>5
              OR EXISTS (
                  SELECT 1
                  FROM sys.index_columns AS ic
                  WHERE ic.object_id=i.object_id
                    AND ic.index_id=i.index_id
                    AND ic.is_included_column=1
              )
              OR EXISTS (
                  SELECT 1
                  FROM sys.index_columns AS ic
                  JOIN sys.columns AS c
                    ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                  WHERE ic.object_id=i.object_id
                    AND ic.index_id=i.index_id
                    AND ic.is_included_column=0
                    AND (
                        (ic.key_ordinal=1 AND c.name<>'ProductionID')
                        OR (ic.key_ordinal=2 AND c.name<>'EquipmentCode')
                        OR (ic.key_ordinal=3 AND c.name<>'ShiftID')
                        OR (ic.key_ordinal=4 AND c.name<>'TimeType')
                        OR (ic.key_ordinal=5 AND c.name<>'SourceType')
                        OR ic.key_ordinal NOT BETWEEN 1 AND 5
                    )
              )
          )
    )
        THROW 51000, 'Existing MANUAL Shift identity index has an unexpected definition.', 1;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name IN ('UX_EquipmentTimeEvent_SummaryIdentity',
                       'UX_EquipmentTimeEvent_ManualShiftIdentity')
    )
        THROW 51000, 'Expected EquipmentTimeEvent identity index is missing.', 1;

    IF COL_LENGTH('dbo.EquipmentTimeEvent', 'ShiftID') IS NULL
        ALTER TABLE dbo.EquipmentTimeEvent
            ADD ShiftID int NULL;

    IF EXISTS (
        SELECT 1
        FROM sys.default_constraints AS dc
        JOIN sys.columns AS c
          ON c.object_id=dc.parent_object_id
         AND c.column_id=dc.parent_column_id
        WHERE dc.parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND c.name='ShiftID'
    )
        THROW 51000, 'ShiftID must not have a default constraint.', 1;

    DECLARE @sql nvarchar(max);

    /* ShiftID-dependent DML is compiled only after the conditional ADD. */
    SET @sql = N'
        UPDATE dbo.EquipmentTimeEvent
        SET ShiftID = @Shift
        WHERE SourceType = @Source
          AND ShiftID IS NULL;';
    EXEC sys.sp_executesql
        @sql,
        N'@Shift int, @Source varchar(20)',
        @Shift=1,
        @Source='MANUAL';

    SET @sql = N'
        IF EXISTS (
            SELECT 1
            FROM dbo.EquipmentTimeEvent
            WHERE SourceType = @Source
              AND (ShiftID IS NULL OR ShiftID NOT IN (1, 2))
        )
            THROW 51000, ''MANUAL EquipmentTimeEvent rows have invalid ShiftID values.'', 1;';
    EXEC sys.sp_executesql
        @sql,
        N'@Source varchar(20)',
        @Source='MANUAL';

    SET @sql = N'
        IF EXISTS (
            SELECT ProductionID, EquipmentCode, ShiftID, TimeType, SourceType
            FROM dbo.EquipmentTimeEvent
            WHERE SourceType = @Source
            GROUP BY ProductionID, EquipmentCode, ShiftID, TimeType, SourceType
            HAVING COUNT(*) > 1
        )
            THROW 51000, ''Duplicate MANUAL EquipmentTimeEvent shift identities exist.'', 1;';
    EXEC sys.sp_executesql
        @sql,
        N'@Source varchar(20)',
        @Source='MANUAL';

    IF EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='UX_EquipmentTimeEvent_SummaryIdentity'
    )
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM sys.indexes
            WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
              AND name='UX_EquipmentTimeEvent_ManualShiftIdentity'
        )
            DROP INDEX UX_EquipmentTimeEvent_SummaryIdentity
                ON dbo.EquipmentTimeEvent;
        ELSE
        BEGIN
            DROP INDEX UX_EquipmentTimeEvent_SummaryIdentity
                ON dbo.EquipmentTimeEvent;

            SET @sql = N'
                CREATE UNIQUE INDEX UX_EquipmentTimeEvent_ManualShiftIdentity
                ON dbo.EquipmentTimeEvent
                   (ProductionID, EquipmentCode, ShiftID, TimeType, SourceType)
                WHERE SourceType = ''MANUAL'';';
            EXEC sys.sp_executesql @sql;
        END;
    END
    ELSE IF NOT EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='UX_EquipmentTimeEvent_ManualShiftIdentity'
    )
        THROW 51000, 'MANUAL Shift identity index is missing after migration preparation.', 1;

    IF EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='CK_EquipmentTimeEvent_ShiftID'
          AND (
              LOWER(definition) NOT LIKE '%shiftid%'
              OR LOWER(definition) NOT LIKE '%is null%'
              OR definition NOT LIKE '%1%'
              OR definition NOT LIKE '%2%'
          )
    )
        THROW 51000, 'Existing ShiftID constraint has an unexpected definition.', 1;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='CK_EquipmentTimeEvent_ShiftID'
    )
    BEGIN
        SET @sql = N'
            ALTER TABLE dbo.EquipmentTimeEvent
            ADD CONSTRAINT CK_EquipmentTimeEvent_ShiftID
                CHECK (ShiftID IS NULL OR ShiftID IN (1, 2));';
        EXEC sys.sp_executesql @sql;
    END;

    IF EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='CK_EquipmentTimeEvent_ManualShift'
          AND (
              LOWER(definition) NOT LIKE '%sourcetype%'
              OR LOWER(definition) NOT LIKE '%manual%'
              OR LOWER(definition) NOT LIKE '%shiftid%'
              OR definition NOT LIKE '%1%'
              OR definition NOT LIKE '%2%'
          )
    )
        THROW 51000, 'Existing MANUAL Shift constraint has an unexpected definition.', 1;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='CK_EquipmentTimeEvent_ManualShift'
    )
    BEGIN
        SET @sql = N'
            ALTER TABLE dbo.EquipmentTimeEvent
            ADD CONSTRAINT CK_EquipmentTimeEvent_ManualShift
                CHECK (SourceType <> ''MANUAL''
                       OR (ShiftID IS NOT NULL AND ShiftID IN (1, 2)));';
        EXEC sys.sp_executesql @sql;
    END;

    /* Final static metadata checks do not bind to ShiftID as a table column. */
    IF NOT EXISTS (
        SELECT 1
        FROM sys.indexes
        WHERE object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='UX_EquipmentTimeEvent_ManualShiftIdentity'
          AND is_unique=1
          AND filter_definition IS NOT NULL
    )
        THROW 51000, 'MANUAL Shift identity index was not created.', 1;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='CK_EquipmentTimeEvent_ShiftID'
          AND is_disabled=0
    )
        THROW 51000, 'ShiftID constraint was not created or is disabled.', 1;

    IF NOT EXISTS (
        SELECT 1
        FROM sys.check_constraints
        WHERE parent_object_id=OBJECT_ID('dbo.EquipmentTimeEvent')
          AND name='CK_EquipmentTimeEvent_ManualShift'
          AND is_disabled=0
    )
        THROW 51000, 'MANUAL Shift constraint was not created or is disabled.', 1;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
