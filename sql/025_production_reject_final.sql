SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
       OR OBJECT_ID(N'dbo.RejectReason', N'U') IS NULL
       OR OBJECT_ID(N'dbo.RejectReasonProductFamily', N'U') IS NULL
       OR OBJECT_ID(N'dbo.ProductionData', N'U') IS NULL
        THROW 52500, 'Required Production or REJECT master tables are missing.', 1;

    IF COL_LENGTH(N'dbo.ProductionLot', N'ProductionID') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'ProdDate') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'ProductFamilyID') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'IsActive') IS NULL
       OR COL_LENGTH(N'dbo.RejectReason', N'id') IS NULL
       OR COL_LENGTH(N'dbo.ProductionData', N'CounterQty') IS NULL
       OR COL_LENGTH(N'dbo.ProductionData', N'CuringQty') IS NULL
        THROW 52501, 'A required Production or REJECT column is missing.', 1;

    IF OBJECT_ID(N'dbo.ProductionRejectFinal', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.ProductionRejectFinalDetail', N'U') IS NOT NULL
        THROW 52502, 'A Production REJECT FINAL target table already exists.', 1;

    CREATE TABLE dbo.ProductionRejectFinal
    (
        ProductionRejectFinalID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_ProductionRejectFinal PRIMARY KEY,
        CreatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_ProductionRejectFinal_CreatedAt DEFAULT SYSDATETIME(),
        UpdatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_ProductionRejectFinal_UpdatedAt DEFAULT SYSDATETIME(),
        ProductionID bigint NOT NULL,
        ProductionDate date NOT NULL,
        Remark nvarchar(1000) NULL,
        TotalWetRejectAtSave bigint NOT NULL,
        RawTotalQtyAtSave bigint NOT NULL,
        FinalClassifiedQtyAtSave bigint NOT NULL,
        UnclassifiedQtyAtSave bigint NOT NULL,
        CONSTRAINT UQ_ProductionRejectFinal_ProductionID
            UNIQUE (ProductionID),
        CONSTRAINT FK_ProductionRejectFinal_Lot
            FOREIGN KEY (ProductionID)
            REFERENCES dbo.ProductionLot(ProductionID),
        CONSTRAINT CK_ProductionRejectFinal_Totals
            CHECK
            (
                TotalWetRejectAtSave >= 0
                AND RawTotalQtyAtSave >= 0
                AND FinalClassifiedQtyAtSave >= 0
                AND UnclassifiedQtyAtSave >= 0
            )
    );

    CREATE TABLE dbo.ProductionRejectFinalDetail
    (
        ProductionRejectFinalDetailID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_ProductionRejectFinalDetail PRIMARY KEY,
        CreatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_ProductionRejectFinalDetail_CreatedAt DEFAULT SYSDATETIME(),
        ProductionRejectFinalID bigint NOT NULL,
        RejectReasonID bigint NOT NULL,
        RawQtyAtSave bigint NOT NULL,
        FinalQty bigint NOT NULL,
        CONSTRAINT UQ_ProductionRejectFinalDetail_HeaderReason
            UNIQUE (ProductionRejectFinalID,RejectReasonID),
        CONSTRAINT FK_ProductionRejectFinalDetail_Header
            FOREIGN KEY (ProductionRejectFinalID)
            REFERENCES dbo.ProductionRejectFinal(ProductionRejectFinalID),
        CONSTRAINT FK_ProductionRejectFinalDetail_RejectReason
            FOREIGN KEY (RejectReasonID)
            REFERENCES dbo.RejectReason(id),
        CONSTRAINT CK_ProductionRejectFinalDetail_Quantities
            CHECK (RawQtyAtSave >= 0 AND FinalQty >= 0)
    );

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
