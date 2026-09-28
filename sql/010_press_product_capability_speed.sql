SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('dbo.PressProductCapability', 'StandardSpeed') IS NULL
    ALTER TABLE dbo.PressProductCapability ADD StandardSpeed decimal(10,2) NULL;

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('dbo.PressProductCapability')
      AND name = 'CK_PressProductCapability_StandardSpeed'
)
    ALTER TABLE dbo.PressProductCapability ADD CONSTRAINT CK_PressProductCapability_StandardSpeed
        CHECK (StandardSpeed IS NULL OR StandardSpeed > 0);

IF OBJECT_ID('dbo.sp_SetPressProductCapabilitySpeed', 'P') IS NULL
    EXEC('CREATE PROCEDURE dbo.sp_SetPressProductCapabilitySpeed AS BEGIN SET NOCOUNT ON; END');
GO

CREATE OR ALTER PROCEDURE dbo.sp_SetPressProductCapabilitySpeed
    @PressEquipmentCode varchar(20),
    @ProductFamily varchar(30),
    @ProductCode varchar(2),
    @StandardSpeed decimal(10,2)
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    IF @StandardSpeed IS NULL OR @StandardSpeed <= 0
        THROW 51001, 'StandardSpeed must be greater than zero.', 1;
    UPDATE dbo.PressProductCapability
    SET StandardSpeed=@StandardSpeed, UpdatedAt=SYSDATETIME()
    WHERE PressEquipmentCode=@PressEquipmentCode
      AND ProductFamily=@ProductFamily
      AND ProductCode=@ProductCode;
    IF @@ROWCOUNT <> 1
        THROW 51002, 'Press product capability was not found.', 1;
END;
GO

COMMIT TRANSACTION;