SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23_TEST'
    THROW 53210, 'Shift Management test seeding may only run in SB23_TEST.', 1;

IF OBJECT_ID(N'dbo.ShiftMasterVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ShiftPeriodVersion', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionDateCutoffVersion', N'U') IS NULL
   OR COL_LENGTH(N'dbo.PressProduction', N'ShiftPeriodID') IS NULL
    THROW 53211, 'Apply Migration 030 in the approved test database before seeding.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    DECLARE @test_date date;
    SELECT @test_date = MIN(EffectiveFromDate)
    FROM dbo.ProductionDateCutoffVersion
    WHERE CutoffTime = '07:00';

    IF @test_date IS NULL
        THROW 53212, 'The effective-dated 07:00 cutoff version is missing.', 1;

    DECLARE @fixture TABLE (
        ProductionID int NOT NULL PRIMARY KEY,
        ShiftMasterID bigint NOT NULL,
        ShiftPeriodID bigint NOT NULL,
        ShiftMasterVersionID bigint NOT NULL,
        ShiftPeriodVersionID bigint NOT NULL,
        CutoffVersionID bigint NOT NULL,
        ShiftCode varchar(10) NOT NULL,
        PeriodLabel nvarchar(100) NOT NULL,
        StartTime time(0) NOT NULL,
        EndTime time(0) NOT NULL
    );

    INSERT @fixture
        (ProductionID, ShiftMasterID, ShiftPeriodID, ShiftMasterVersionID,
         ShiftPeriodVersionID, CutoffVersionID, ShiftCode, PeriodLabel,
         StartTime, EndTime)
    SELECT test.ProductionID, shift.id, period.ShiftPeriodID,
           shift_version.id, period.id, cutoff.id, shift.ShiftCode,
           period.PeriodLabel, period.StartTime, period.EndTime
    FROM (VALUES
        (990010, CONVERT(varchar(10), '1'), CONVERT(time(0), '08:00'), CONVERT(time(0), '16:00')),
        (990011, CONVERT(varchar(10), '1'), CONVERT(time(0), '16:00'), CONVERT(time(0), '18:00')),
        (990012, CONVERT(varchar(10), '2'), CONVERT(time(0), '04:00'), CONVERT(time(0), '08:00'))
    ) AS test(ProductionID, ShiftCode, StartTime, EndTime)
    JOIN dbo.ShiftMaster AS shift
      ON shift.ShiftCode = test.ShiftCode
    CROSS APPLY (
        SELECT TOP (1) version_row.id
        FROM dbo.ShiftMasterVersion AS version_row
        WHERE version_row.ShiftMasterID = shift.id
          AND version_row.EffectiveFromDate <= @test_date
          AND (version_row.EffectiveToDate IS NULL OR version_row.EffectiveToDate >= @test_date)
        ORDER BY version_row.EffectiveFromDate DESC, version_row.VersionNumber DESC
    ) AS shift_version
    CROSS APPLY (
        SELECT TOP (1) period_master.id AS ShiftPeriodID,
               period_version.id, period_version.PeriodLabel,
               period_version.StartTime, period_version.EndTime
        FROM dbo.ShiftPeriodMaster AS period_master
        JOIN dbo.ShiftPeriodVersion AS period_version
          ON period_version.ShiftPeriodID = period_master.id
        WHERE period_master.ShiftMasterID = shift.id
          AND period_version.StartTime = test.StartTime
          AND period_version.EndTime = test.EndTime
          AND period_version.IsActive = 1
          AND period_version.EffectiveFromDate <= @test_date
          AND (period_version.EffectiveToDate IS NULL OR period_version.EffectiveToDate >= @test_date)
        ORDER BY period_version.EffectiveFromDate DESC, period_version.VersionNumber DESC
    ) AS period
    CROSS APPLY (
        SELECT TOP (1) cutoff_row.id
        FROM dbo.ProductionDateCutoffVersion AS cutoff_row
        WHERE cutoff_row.CutoffTime = '07:00'
          AND cutoff_row.EffectiveFromDate <= @test_date
          AND (cutoff_row.EffectiveToDate IS NULL OR cutoff_row.EffectiveToDate >= @test_date)
        ORDER BY cutoff_row.EffectiveFromDate DESC, cutoff_row.VersionNumber DESC
    ) AS cutoff;

    IF (SELECT COUNT(*) FROM @fixture) <> 3
        THROW 53213, 'The required synthetic Shift period versions were not resolved.', 1;

    UPDATE lot
    SET ProdDate = @test_date,
        ShiftMasterID = fixture.ShiftMasterID,
        ShiftCodeSnapshot = fixture.ShiftCode,
        ProductionDateCutoffVersionID = fixture.CutoffVersionID,
        ProductionDateCutoffSnapshot = '07:00'
    FROM dbo.ProductionLot AS lot
    JOIN @fixture AS fixture ON fixture.ProductionID = lot.ProductionID;

    IF @@ROWCOUNT <> 3
        THROW 53214, 'Expected exactly three synthetic ProductionLot rows.', 1;

    UPDATE assignment
    SET ShiftMasterID = fixture.ShiftMasterID,
        ShiftPeriodID = fixture.ShiftPeriodID,
        ShiftMasterVersionID = fixture.ShiftMasterVersionID,
        ShiftPeriodVersionID = fixture.ShiftPeriodVersionID,
        ShiftCodeSnapshot = fixture.ShiftCode,
        PeriodLabelSnapshot = fixture.PeriodLabel,
        PeriodStartTimeSnapshot = fixture.StartTime,
        PeriodEndTimeSnapshot = fixture.EndTime,
        ProductionDateCutoffVersionID = fixture.CutoffVersionID,
        ProductionDateCutoffSnapshot = '07:00',
        ProductionStartTime = DATEADD(
            SECOND, DATEDIFF(SECOND, CONVERT(time(0), '00:00'), fixture.StartTime),
            CONVERT(datetime2(0), @test_date)),
        ProductionEndTime = DATEADD(
            SECOND, DATEDIFF(SECOND, CONVERT(time(0), '00:00'), fixture.EndTime),
            CONVERT(datetime2(0), @test_date))
    FROM dbo.PressProduction AS assignment
    JOIN @fixture AS fixture ON fixture.ProductionID = assignment.ProductionID
    WHERE assignment.MachineCode IN (N'F_TEST_SHIFT1', N'F_TEST_SHIFT2');

    IF @@ROWCOUNT <> 3
        THROW 53215, 'Expected exactly three synthetic Press assignments.', 1;

    UPDATE dbo.DailyMaterialUsage SET ReportDate = @test_date
    WHERE MaterialUsageID = 990001;
    UPDATE dbo.LoggerEvent SET ProductionDate = @test_date
    WHERE StopId = 99001 AND ShiftID = 1;
    UPDATE dbo.ProductionRejectEntry SET ProductionDate = @test_date
    WHERE Shift = '1' AND RejectQty = 5;
    UPDATE dbo.DepalletRejectEntry SET ProductionDate = @test_date
    WHERE Shift = '1' AND RejectQty = 7 AND LineEquipmentID = 99001;

    COMMIT TRANSACTION;

    SELECT lot.ProductionID, lot.ProdDate, lot.ShiftMasterID,
           lot.ShiftCodeSnapshot, lot.ProductionDateCutoffSnapshot,
           assignment.ShiftPeriodID, assignment.PeriodLabelSnapshot,
           assignment.PeriodStartTimeSnapshot, assignment.PeriodEndTimeSnapshot,
           assignment.ProductionStartTime, assignment.ProductionEndTime
    FROM dbo.ProductionLot AS lot
    JOIN dbo.PressProduction AS assignment
      ON assignment.ProductionID = lot.ProductionID
    WHERE lot.ProductionID IN (990010, 990011, 990012)
    ORDER BY lot.ProductionID;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
