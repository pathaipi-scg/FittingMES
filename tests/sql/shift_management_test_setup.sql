SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23_TEST'
    THROW 53200, 'Shift Management test setup may only run in SB23_TEST.', 1;

IF EXISTS (SELECT 1 FROM sys.objects WHERE is_ms_shipped = 0)
   OR EXISTS (SELECT 1 FROM sys.synonyms)
   OR EXISTS (
       SELECT 1
       FROM sys.sql_expression_dependencies
       WHERE referenced_database_name IS NOT NULL
          OR referenced_server_name IS NOT NULL
   )
    THROW 53201, 'SB23_TEST must be empty and have no external dependencies before setup.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    CREATE TABLE dbo.ShiftMaster (
        id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_ShiftMaster PRIMARY KEY,
        ShiftCode varchar(10) NOT NULL,
        ShiftName nvarchar(200) NOT NULL,
        IsActive bit NOT NULL,
        CONSTRAINT UQ_ShiftMaster_ShiftCode UNIQUE (ShiftCode)
    );

    CREATE TABLE dbo.ProductionDayRuleHistory (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_ProductionDayRuleHistory PRIMARY KEY,
        EffectiveFromDate date NOT NULL,
        DayStartTime time(0) NOT NULL,
        CONSTRAINT UQ_ProductionDayRuleHistory_Effective UNIQUE (EffectiveFromDate)
    );

    CREATE TABLE dbo.ProductionLot (
        ProductionID int NOT NULL CONSTRAINT PK_ProductionLot PRIMARY KEY,
        LotNo nvarchar(40) NOT NULL CONSTRAINT UQ_ProductionLot_LotNo UNIQUE,
        ProdDate date NOT NULL,
        IsActive bit NOT NULL,
        Shift varchar(10) NULL
    );

    CREATE TABLE dbo.ProductionData (
        ProductionID int NOT NULL CONSTRAINT PK_ProductionData PRIMARY KEY,
        CounterQty int NOT NULL,
        CuringQty int NOT NULL,
        CONSTRAINT FK_TestProductionData_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID)
    );

    CREATE TABLE dbo.PressProduction (
        PressProductionID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_PressProduction PRIMARY KEY,
        ProductionID int NOT NULL,
        MachineCode nvarchar(30) NOT NULL,
        MouldID int NULL,
        ShiftMasterID bigint NULL,
        ReleasedAt datetime2(0) NULL,
        ProductionStartTime datetime2(0) NULL,
        ProductionEndTime datetime2(0) NULL,
        DispatchQty int NULL,
        CounterQty int NULL,
        CuringQty int NULL,
        DowntimeMinutes decimal(10,2) NULL,
        Remark nvarchar(255) NULL,
        CONSTRAINT FK_TestPressProduction_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID),
        CONSTRAINT FK_PressProduction_ShiftMaster
            FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id)
    );

    CREATE UNIQUE INDEX UX_PressProduction_Production_Machine_ShiftActive
        ON dbo.PressProduction (ProductionID, MachineCode, ShiftMasterID)
        WHERE ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL;

    CREATE TABLE dbo.DailyMaterialUsage (
        MaterialUsageID int NOT NULL CONSTRAINT PK_DailyMaterialUsage PRIMARY KEY,
        ReportDate date NOT NULL,
        Shift varchar(10) NOT NULL
    );

    CREATE TABLE dbo.MaterialUsageMaster (
        MaterialUsageCode varchar(40) NOT NULL
            CONSTRAINT PK_MaterialUsageMaster PRIMARY KEY,
        MaterialNameTH nvarchar(200) NOT NULL,
        MaterialNameEN nvarchar(200) NOT NULL,
        Unit nvarchar(40) NOT NULL,
        SortOrder int NOT NULL,
        APIFieldCode varchar(40) NOT NULL,
        UsageType varchar(20) NOT NULL
    );

    CREATE TABLE dbo.DailyMaterialUsageDetail (
        MaterialUsageID int NOT NULL,
        MaterialUsageCode varchar(40) NOT NULL,
        Qty decimal(18,3) NOT NULL,
        SourceType varchar(40) NULL,
        Remark nvarchar(255) NULL,
        CONSTRAINT PK_DailyMaterialUsageDetail
            PRIMARY KEY (MaterialUsageID, MaterialUsageCode),
        CONSTRAINT FK_TestUsageDetail_Header
            FOREIGN KEY (MaterialUsageID) REFERENCES dbo.DailyMaterialUsage(MaterialUsageID),
        CONSTRAINT FK_TestUsageDetail_Master
            FOREIGN KEY (MaterialUsageCode) REFERENCES dbo.MaterialUsageMaster(MaterialUsageCode)
    );

    CREATE TABLE dbo.LoggerEvent (
        LoggerEventID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_LoggerEvent PRIMARY KEY,
        ProductionDate date NOT NULL,
        ShiftID int NULL,
        DurationMin decimal(10,2) NOT NULL,
        StopId int NULL
    );

    CREATE TABLE dbo.ProductionRejectEntry (
        ProductionRejectEntryID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_ProductionRejectEntry PRIMARY KEY,
        ProductionDate date NOT NULL,
        Shift varchar(10) NULL,
        RejectQty int NOT NULL
    );

    CREATE TABLE dbo.DepalletRejectEntry (
        EntryID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_DepalletRejectEntry PRIMARY KEY,
        ProductionDate date NOT NULL,
        Shift varchar(10) NULL,
        RejectQty int NOT NULL,
        LineEquipmentID bigint NULL
    );

    INSERT dbo.ShiftMaster (ShiftCode, ShiftName, IsActive)
    VALUES ('1', N'Shift 1', 1), ('2', N'Shift 2', 1);

    INSERT dbo.ProductionDayRuleHistory (EffectiveFromDate, DayStartTime)
    VALUES ('2026-01-01', '08:00');

    INSERT dbo.ProductionLot (ProductionID, LotNo, ProdDate, IsActive, Shift)
    VALUES
        (990001, N'TEST029_HIST_INVALID', '20260903', 1, '1'),
        (990002, N'TEST029_HIST_OVERLAP', '20260904', 1, '1'),
        (990010, N'TEST_SHIFT1_PERIOD1', '20261107', 1, '1'),
        (990011, N'TEST_SHIFT1_PERIOD2', '20261107', 1, '1'),
        (990012, N'TEST_SHIFT2_CUTOFF', '20261107', 1, '2');

    INSERT dbo.ProductionData (ProductionID, CounterQty, CuringQty)
    VALUES (990010, 100, 80), (990011, 200, 160), (990012, 300, 240);

    DECLARE @shift1 bigint = (SELECT id FROM dbo.ShiftMaster WHERE ShiftCode = '1');
    DECLARE @shift2 bigint = (SELECT id FROM dbo.ShiftMaster WHERE ShiftCode = '2');

    INSERT dbo.PressProduction
        (ProductionID, MachineCode, MouldID, ShiftMasterID, ReleasedAt,
         ProductionStartTime, ProductionEndTime, DispatchQty, CounterQty,
         CuringQty, DowntimeMinutes, Remark)
    VALUES
        (990001, N'F_LEGACY_INVALID', 99001, @shift1, NULL,
         NULL, NULL, 1, 1, 1, 0, N'Synthetic unresolved legacy row'),
        (990002, N'F_LEGACY_OVERLAP', 99002, @shift1, NULL,
         '2026-09-04T08:00:00', '2026-09-04T16:00:00', 1, 1, 1, 0,
         N'Synthetic legacy overlap A'),
        (990002, N'F_LEGACY_OVERLAP', 99002, @shift2, NULL,
         '2026-09-04T08:00:00', '2026-09-04T16:00:00', 1, 1, 1, 0,
         N'Synthetic legacy overlap B'),
        (990010, N'F_TEST_SHIFT1', 99010, @shift1, NULL,
         '2026-11-07T08:00:00', '2026-11-07T16:00:00', 100, 100, 80, 0,
         N'Synthetic Shift 1 first period'),
        (990011, N'F_TEST_SHIFT1', 99010, @shift1, NULL,
         '2026-11-07T16:00:00', '2026-11-07T18:00:00', 200, 200, 160, 0,
         N'Synthetic Shift 1 second period'),
        (990012, N'F_TEST_SHIFT2', 99012, @shift2, NULL,
         '2026-11-07T04:00:00', '2026-11-07T08:00:00', 300, 300, 240, 0,
         N'Synthetic Shift 2 period crossing the cutoff');

    INSERT dbo.MaterialUsageMaster
        (MaterialUsageCode, MaterialNameTH, MaterialNameEN, Unit, SortOrder,
         APIFieldCode, UsageType)
    VALUES
        ('TEST_MATERIAL', N'วัสดุทดสอบ', N'Test material', N'kg', 1,
         'TEST_MATERIAL', 'MATERIAL');

    INSERT dbo.DailyMaterialUsage (MaterialUsageID, ReportDate, Shift)
    VALUES (990001, '20261107', '1');

    INSERT dbo.DailyMaterialUsageDetail
        (MaterialUsageID, MaterialUsageCode, Qty, SourceType, Remark)
    VALUES (990001, 'TEST_MATERIAL', 12.5, 'TEST', N'Synthetic report fixture');

    INSERT dbo.LoggerEvent (ProductionDate, ShiftID, DurationMin, StopId)
    VALUES ('20261107', 1, 15, 99001);

    INSERT dbo.ProductionRejectEntry (ProductionDate, Shift, RejectQty)
    VALUES ('20261107', '1', 5);

    INSERT dbo.DepalletRejectEntry
        (ProductionDate, Shift, RejectQty, LineEquipmentID)
    VALUES ('20261107', '1', 7, 99001);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
