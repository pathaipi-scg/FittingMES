SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23_TEST'
    THROW 52900, 'Test schema may only be installed in SB23_TEST.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NOT NULL
    THROW 52901, 'Test schema already exists; use the documented cleanup first.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    CREATE TABLE dbo.ProductionLot (
        ProductionID int NOT NULL PRIMARY KEY,
        LotNo nvarchar(40) NOT NULL,
        ProdDate date NOT NULL,
        IsActive bit NOT NULL
    );

    CREATE TABLE dbo.PressProduction (
        PressProductionID bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
        ProductionID int NOT NULL,
        MachineCode nvarchar(30) NOT NULL,
        MouldID int NULL,
        ShiftMasterID int NULL,
        ReleasedAt datetime2(0) NULL,
        ProductionStartTime datetime2(0) NULL,
        ProductionEndTime datetime2(0) NULL,
        DispatchQty int NULL,
        CounterQty int NULL,
        CuringQty int NULL,
        DowntimeMinutes decimal(10,2) NULL,
        Remark nvarchar(255) NULL,
        CONSTRAINT FK_TestPressProduction_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID)
    );

    CREATE UNIQUE INDEX UX_PressProduction_Production_Machine_ShiftActive
        ON dbo.PressProduction (ProductionID, MachineCode, ShiftMasterID)
        WHERE ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL;

    INSERT INTO dbo.ProductionLot (ProductionID, LotNo, ProdDate, IsActive)
    VALUES
        (990001, N'TEST029_HIST_INVALID', '20260903', 1),
        (990002, N'TEST029_HIST_OVERLAP', '20260904', 1);

    INSERT INTO dbo.PressProduction
        (ProductionID, MachineCode, MouldID, ShiftMasterID, ReleasedAt,
         ProductionStartTime, ProductionEndTime, DispatchQty, CounterQty,
         CuringQty, DowntimeMinutes, Remark)
    VALUES
        (990001, N'F_LEGACY_INVALID', 99001, 1, NULL,
         NULL, NULL, 1, 1, 1, 0, N'Synthetic unresolved legacy row'),
        (990002, N'F_LEGACY_OVERLAP', 99002, 1, NULL,
         '2026-09-04T08:00:00', '2026-09-04T16:00:00', 1, 1, 1, 0,
         N'Synthetic legacy overlap A'),
        (990002, N'F_LEGACY_OVERLAP', 99002, 2, NULL,
         '2026-09-04T08:00:00', '2026-09-04T16:00:00', 1, 1, 1, 0,
         N'Synthetic legacy overlap B');

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
