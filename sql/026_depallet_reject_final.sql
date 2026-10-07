SET XACT_ABORT ON;

IF DB_NAME() <> N'SB23'
    THROW 52600, 'Migration 026 is destructive and may only be applied to SB23.', 1;

IF OBJECT_ID(N'dbo.Depallet', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
   OR OBJECT_ID(N'dbo.RejectReason', N'U') IS NULL
   OR OBJECT_ID(N'dbo.DepalletRejectEntry', N'U') IS NULL
    THROW 52601, 'A required Depallet or REJECT table is missing.', 1;

DECLARE @DepalletIDType sysname;
SELECT @DepalletIDType = TYPE_NAME(user_type_id)
FROM sys.columns
WHERE object_id=OBJECT_ID(N'dbo.Depallet') AND name=N'DepalletID';

IF @DepalletIDType IS NULL OR @DepalletIDType NOT IN (N'int',N'bigint')
    THROW 52602, 'dbo.Depallet.DepalletID must use int or bigint before applying migration 026.', 1;

IF OBJECT_ID(N'dbo.DepalletRejectFinal', N'U') IS NOT NULL
   OR OBJECT_ID(N'dbo.DepalletRejectFinalDetail', N'U') IS NOT NULL
    THROW 52603, 'A Depallet REJECT FINAL target table already exists.', 1;

BEGIN TRY
    BEGIN TRANSACTION;

    DROP TABLE dbo.DepalletRejectEntry;

    CREATE TABLE dbo.DepalletRejectEntry
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_DepalletRejectEntry PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_DepalletRejectEntry_Rectime DEFAULT (GETDATE()),
        ProductionDate date NOT NULL,
        ShiftID bigint NOT NULL,
        LineEquipmentID bigint NOT NULL,
        SourceEquipmentID bigint NULL,
        RejectSourceScopeID bigint NOT NULL,
        ProductionID bigint NOT NULL,
        RejectReasonID bigint NOT NULL,
        Qty int NOT NULL,
        CONSTRAINT CK_DepalletRejectEntry_Qty CHECK (Qty > 0),
        CONSTRAINT FK_DepalletRejectEntry_Shift
            FOREIGN KEY (ShiftID) REFERENCES dbo.ShiftMaster(id),
        CONSTRAINT FK_DepalletRejectEntry_LineEquipment
            FOREIGN KEY (LineEquipmentID) REFERENCES dbo.EquipmentMaster(id),
        CONSTRAINT FK_DepalletRejectEntry_SourceEquipment
            FOREIGN KEY (SourceEquipmentID) REFERENCES dbo.EquipmentMaster(id),
        CONSTRAINT FK_DepalletRejectEntry_SourceScope
            FOREIGN KEY (RejectSourceScopeID) REFERENCES dbo.RejectSourceScope(id),
        CONSTRAINT FK_DepalletRejectEntry_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID),
        CONSTRAINT FK_DepalletRejectEntry_Reason
            FOREIGN KEY (RejectReasonID) REFERENCES dbo.RejectReason(id)
    );

    DECLARE @DepalletEntryKeyDDL nvarchar(max) =
        N'ALTER TABLE dbo.DepalletRejectEntry ADD DepalletID '
        + QUOTENAME(@DepalletIDType) + N' NOT NULL;';
    EXEC sys.sp_executesql @DepalletEntryKeyDDL;

    ALTER TABLE dbo.DepalletRejectEntry
        ADD CONSTRAINT FK_DepalletRejectEntry_Depallet
        FOREIGN KEY (DepalletID) REFERENCES dbo.Depallet(DepalletID);

    CREATE INDEX IX_DepalletRejectEntry_CAL
        ON dbo.DepalletRejectEntry (DepalletID,ShiftID)
        INCLUDE (ProductionDate,ProductionID,LineEquipmentID,
                 SourceEquipmentID,RejectReasonID,RejectSourceScopeID,Qty);
    CREATE INDEX IX_DepalletRejectEntry_ProductionID
        ON dbo.DepalletRejectEntry (ProductionID);
    CREATE INDEX IX_DepalletRejectEntry_LineDate
        ON dbo.DepalletRejectEntry (LineEquipmentID,ProductionDate,ShiftID);
    CREATE INDEX IX_DepalletRejectEntry_SourceDate
        ON dbo.DepalletRejectEntry (SourceEquipmentID,ProductionDate,ShiftID)
        WHERE SourceEquipmentID IS NOT NULL;
    CREATE INDEX IX_DepalletRejectEntry_Reason
        ON dbo.DepalletRejectEntry (RejectReasonID);

    CREATE TABLE dbo.DepalletRejectFinal
    (
        DepalletRejectFinalID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_DepalletRejectFinal PRIMARY KEY,
        CreatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_DepalletRejectFinal_CreatedAt DEFAULT SYSDATETIME(),
        UpdatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_DepalletRejectFinal_UpdatedAt DEFAULT SYSDATETIME(),
        ProductionID bigint NOT NULL,
        DepalletDate date NOT NULL,
        Remark nvarchar(1000) NULL,
        TotalRejectAtSave bigint NOT NULL,
        RawTotalQtyAtSave bigint NOT NULL,
        FinalClassifiedQtyAtSave bigint NOT NULL,
        UnclassifiedQtyAtSave bigint NOT NULL,
        CONSTRAINT FK_DepalletRejectFinal_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID),
        CONSTRAINT CK_DepalletRejectFinal_Totals
            CHECK
            (
                TotalRejectAtSave >= 0
                AND RawTotalQtyAtSave >= 0
                AND FinalClassifiedQtyAtSave >= 0
                AND UnclassifiedQtyAtSave >= 0
            )
    );

    DECLARE @DepalletFinalKeyDDL nvarchar(max) =
        N'ALTER TABLE dbo.DepalletRejectFinal ADD DepalletID '
        + QUOTENAME(@DepalletIDType) + N' NOT NULL;';
    EXEC sys.sp_executesql @DepalletFinalKeyDDL;

    ALTER TABLE dbo.DepalletRejectFinal
        ADD CONSTRAINT UQ_DepalletRejectFinal_DepalletID UNIQUE (DepalletID);
    ALTER TABLE dbo.DepalletRejectFinal
        ADD CONSTRAINT FK_DepalletRejectFinal_Depallet
        FOREIGN KEY (DepalletID) REFERENCES dbo.Depallet(DepalletID);

    CREATE TABLE dbo.DepalletRejectFinalDetail
    (
        DepalletRejectFinalDetailID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_DepalletRejectFinalDetail PRIMARY KEY,
        CreatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_DepalletRejectFinalDetail_CreatedAt DEFAULT SYSDATETIME(),
        DepalletRejectFinalID bigint NOT NULL,
        RejectReasonID bigint NOT NULL,
        RawQtyAtSave bigint NOT NULL,
        FinalQty bigint NOT NULL,
        CONSTRAINT UQ_DepalletRejectFinalDetail_HeaderReason
            UNIQUE (DepalletRejectFinalID,RejectReasonID),
        CONSTRAINT FK_DepalletRejectFinalDetail_Header
            FOREIGN KEY (DepalletRejectFinalID)
            REFERENCES dbo.DepalletRejectFinal(DepalletRejectFinalID),
        CONSTRAINT FK_DepalletRejectFinalDetail_RejectReason
            FOREIGN KEY (RejectReasonID) REFERENCES dbo.RejectReason(id),
        CONSTRAINT CK_DepalletRejectFinalDetail_Quantities
            CHECK (RawQtyAtSave >= 0 AND FinalQty >= 0)
    );

    CREATE INDEX IX_DepalletRejectFinalDetail_RejectReason
        ON dbo.DepalletRejectFinalDetail (RejectReasonID)
        INCLUDE (DepalletRejectFinalID,FinalQty);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
