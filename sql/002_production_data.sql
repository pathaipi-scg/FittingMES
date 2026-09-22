SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF OBJECT_ID('dbo.ProductionData','U') IS NULL
CREATE TABLE dbo.ProductionData (
    ProductionID bigint NOT NULL CONSTRAINT PK_ProductionData PRIMARY KEY,
    ProductionStartTime time(0) NOT NULL,
    ProductionEndTime time(0) NOT NULL,
    CounterQty int NOT NULL,
    CuringQty int NOT NULL,
    Remark nvarchar(1000) NULL,
    CreatedAt datetime2(3) NOT NULL CONSTRAINT DF_ProductionData_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt datetime2(3) NOT NULL CONSTRAINT DF_ProductionData_UpdatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT FK_ProductionData_Lot FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID),
    CONSTRAINT CK_ProductionData_Counter CHECK (CounterQty>=0),
    CONSTRAINT CK_ProductionData_Curing CHECK (CuringQty>=0 AND CuringQty<=CounterQty)
);
COMMIT TRANSACTION;
