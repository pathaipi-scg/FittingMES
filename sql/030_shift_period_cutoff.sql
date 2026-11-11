SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_030_TestRun')) = N'1'
   )
    THROW 53000, 'Migration 030 may only be applied to SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.ShiftMaster', N'U') IS NULL
   OR OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
    THROW 53001, 'Required Shift or Production tables are missing.', 1;

IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NOT NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ShiftPeriodID') IS NOT NULL
    THROW 53002, 'Migration 030 target objects already exist; refusing to guess prior state.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    CREATE TABLE dbo.ShiftMasterVersion (
        id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ShiftMasterVersion PRIMARY KEY,
        Rectime datetime NOT NULL CONSTRAINT DF_ShiftMasterVersion_Rectime DEFAULT (GETDATE()),
        ShiftMasterID bigint NOT NULL,
        VersionNumber int NOT NULL,
        ShiftCode varchar(10) NOT NULL,
        ShiftName nvarchar(200) NOT NULL,
        IsActive bit NOT NULL,
        OldValue nvarchar(1000) NOT NULL,
        NewValue nvarchar(1000) NOT NULL,
        ChangedAt datetime2(3) NOT NULL CONSTRAINT DF_ShiftMasterVersion_ChangedAt DEFAULT (SYSDATETIME()),
        ChangedBy nvarchar(256) NULL,
        EffectiveFromDate date NOT NULL,
        EffectiveToDate date NULL,
        ChangeReason nvarchar(1000) NULL,
        CONSTRAINT FK_ShiftMasterVersion_ShiftMaster
            FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id),
        CONSTRAINT UQ_ShiftMasterVersion_Shift_Version UNIQUE (ShiftMasterID, VersionNumber),
        CONSTRAINT UQ_ShiftMasterVersion_Shift_Effective UNIQUE (ShiftMasterID, EffectiveFromDate)
    );

    CREATE TABLE dbo.ShiftPeriodMaster (
        id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ShiftPeriodMaster PRIMARY KEY,
        Rectime datetime NOT NULL CONSTRAINT DF_ShiftPeriodMaster_Rectime DEFAULT (GETDATE()),
        ShiftMasterID bigint NOT NULL,
        CONSTRAINT FK_ShiftPeriodMaster_ShiftMaster
            FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id)
    );

    CREATE TABLE dbo.ShiftPeriodVersion (
        id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ShiftPeriodVersion PRIMARY KEY,
        Rectime datetime NOT NULL CONSTRAINT DF_ShiftPeriodVersion_Rectime DEFAULT (GETDATE()),
        ShiftPeriodID bigint NOT NULL,
        VersionNumber int NOT NULL,
        PeriodLabel nvarchar(100) NOT NULL,
        DisplayOrder int NOT NULL,
        StartTime time(0) NOT NULL,
        EndTime time(0) NOT NULL,
        IsActive bit NOT NULL,
        OldValue nvarchar(1000) NOT NULL,
        NewValue nvarchar(1000) NOT NULL,
        ChangedAt datetime2(3) NOT NULL CONSTRAINT DF_ShiftPeriodVersion_ChangedAt DEFAULT (SYSDATETIME()),
        ChangedBy nvarchar(256) NULL,
        EffectiveFromDate date NOT NULL,
        EffectiveToDate date NULL,
        ChangeReason nvarchar(1000) NULL,
        CONSTRAINT FK_ShiftPeriodVersion_ShiftPeriod
            FOREIGN KEY (ShiftPeriodID) REFERENCES dbo.ShiftPeriodMaster(id),
        CONSTRAINT UQ_ShiftPeriodVersion_Period_Version UNIQUE (ShiftPeriodID, VersionNumber),
        CONSTRAINT UQ_ShiftPeriodVersion_Period_Effective UNIQUE (ShiftPeriodID, EffectiveFromDate),
        CONSTRAINT CK_ShiftPeriodVersion_Time CHECK (StartTime <> EndTime)
    );

    CREATE TABLE dbo.ProductionDateCutoffVersion (
        id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ProductionDateCutoffVersion PRIMARY KEY,
        Rectime datetime NOT NULL CONSTRAINT DF_ProductionDateCutoffVersion_Rectime DEFAULT (GETDATE()),
        VersionNumber int NOT NULL,
        CutoffTime time(0) NOT NULL,
        OldValue nvarchar(1000) NOT NULL,
        NewValue nvarchar(1000) NOT NULL,
        ChangedAt datetime2(3) NOT NULL CONSTRAINT DF_ProductionDateCutoffVersion_ChangedAt DEFAULT (SYSDATETIME()),
        ChangedBy nvarchar(256) NULL,
        EffectiveFromDate date NOT NULL,
        EffectiveToDate date NULL,
        ChangeReason nvarchar(1000) NULL,
        CONSTRAINT UQ_ProductionDateCutoffVersion_Version UNIQUE (VersionNumber),
        CONSTRAINT UQ_ProductionDateCutoffVersion_Effective UNIQUE (EffectiveFromDate)
    );

    ALTER TABLE dbo.PressProduction ADD
        ShiftPeriodID bigint NULL,
        ShiftMasterVersionID bigint NULL,
        ShiftPeriodVersionID bigint NULL,
        ShiftCodeSnapshot varchar(10) NULL,
        PeriodLabelSnapshot nvarchar(100) NULL,
        PeriodStartTimeSnapshot time(0) NULL,
        PeriodEndTimeSnapshot time(0) NULL,
        ProductionDateCutoffVersionID bigint NULL,
        ProductionDateCutoffSnapshot time(0) NULL;

    ALTER TABLE dbo.ProductionLot ADD
        ShiftMasterID bigint NULL,
        ShiftCodeSnapshot varchar(10) NULL,
        ProductionDateCutoffVersionID bigint NULL,
        ProductionDateCutoffSnapshot time(0) NULL;

    ALTER TABLE dbo.PressProduction ADD
        CONSTRAINT FK_PressProduction_ShiftPeriod
            FOREIGN KEY (ShiftPeriodID) REFERENCES dbo.ShiftPeriodMaster(id),
        CONSTRAINT FK_PressProduction_ShiftMasterVersion
            FOREIGN KEY (ShiftMasterVersionID) REFERENCES dbo.ShiftMasterVersion(id),
        CONSTRAINT FK_PressProduction_ShiftPeriodVersion
            FOREIGN KEY (ShiftPeriodVersionID) REFERENCES dbo.ShiftPeriodVersion(id),
        CONSTRAINT FK_PressProduction_CutoffVersion
            FOREIGN KEY (ProductionDateCutoffVersionID) REFERENCES dbo.ProductionDateCutoffVersion(id);

    ALTER TABLE dbo.ProductionLot ADD
        CONSTRAINT FK_ProductionLot_ShiftMaster
            FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id),
        CONSTRAINT FK_ProductionLot_CutoffVersion
            FOREIGN KEY (ProductionDateCutoffVersionID) REFERENCES dbo.ProductionDateCutoffVersion(id);

    DECLARE @configuration_date date =
        CONVERT(date, DATEADD(hour, 7, SYSUTCDATETIME()));
    DECLARE @effective date = DATEADD(day, 1, @configuration_date);
    DECLARE @shift_id bigint, @shift_code varchar(10), @shift_name nvarchar(200);
    DECLARE shift_seed CURSOR LOCAL FAST_FORWARD FOR
        SELECT id, ShiftCode, ShiftName FROM dbo.ShiftMaster;
    OPEN shift_seed;
    FETCH NEXT FROM shift_seed INTO @shift_id, @shift_code, @shift_name;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        INSERT dbo.ShiftMasterVersion
            (ShiftMasterID, VersionNumber, ShiftCode, ShiftName, IsActive,
             OldValue, NewValue, EffectiveFromDate, ChangeReason)
        SELECT @shift_id, 1, @shift_code, @shift_name, IsActive,
               N'<initial>', CONCAT(@shift_code, N'|', @shift_name, N'|',
                                    CONVERT(nvarchar(1), IsActive)),
               @configuration_date, N'Initial versioned Shift configuration'
        FROM dbo.ShiftMaster WHERE id = @shift_id;
        FETCH NEXT FROM shift_seed INTO @shift_id, @shift_code, @shift_name;
    END;
    CLOSE shift_seed;
    DEALLOCATE shift_seed;

    DECLARE @shift1 bigint, @shift2 bigint;
    SELECT @shift1 = id FROM dbo.ShiftMaster WHERE ShiftCode = '1';
    SELECT @shift2 = id FROM dbo.ShiftMaster WHERE ShiftCode = '2';
    IF @shift1 IS NULL OR @shift2 IS NULL
        THROW 53003, 'Initial period seed requires exactly the existing Shift codes 1 and 2.', 1;

    INSERT dbo.ShiftPeriodMaster (ShiftMasterID)
    VALUES (@shift1), (@shift1), (@shift2), (@shift2);

    INSERT dbo.ShiftPeriodVersion
        (ShiftPeriodID, VersionNumber, PeriodLabel, DisplayOrder, StartTime, EndTime,
         IsActive, OldValue, NewValue, EffectiveFromDate, ChangeReason)
    SELECT id, 1, seed.PeriodLabel, seed.DisplayOrder, seed.StartTime, seed.EndTime,
           1, N'<initial>',
           CONCAT(seed.PeriodLabel, N'|', CONVERT(nvarchar(5), seed.StartTime, 108),
                  N'|', CONVERT(nvarchar(5), seed.EndTime, 108), N'|1'),
           @effective, N'Initial versioned Shift Period configuration'
    FROM (VALUES
        (@shift1, N'1', 1, CONVERT(time(0), '08:00'), CONVERT(time(0), '16:00')),
        (@shift1, N'2', 2, CONVERT(time(0), '16:00'), CONVERT(time(0), '18:00')),
        (@shift2, N'1', 1, CONVERT(time(0), '18:00'), CONVERT(time(0), '04:00')),
        (@shift2, N'2', 2, CONVERT(time(0), '04:00'), CONVERT(time(0), '08:00'))
    ) AS seed(ShiftMasterID, PeriodLabel, DisplayOrder, StartTime, EndTime)
    JOIN (
        SELECT ShiftMasterID, id,
               ROW_NUMBER() OVER (PARTITION BY ShiftMasterID ORDER BY id) AS PeriodNumber
        FROM dbo.ShiftPeriodMaster
    ) AS periods
      ON periods.ShiftMasterID = seed.ShiftMasterID
     AND periods.PeriodNumber = seed.DisplayOrder;

    INSERT dbo.ProductionDateCutoffVersion
        (VersionNumber, CutoffTime, OldValue, NewValue, EffectiveFromDate, ChangeReason)
    VALUES
        (1, '07:00', N'<initial>', N'07:00 Asia/Bangkok',
         @effective, N'Initial configurable Production Date cutoff');

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
