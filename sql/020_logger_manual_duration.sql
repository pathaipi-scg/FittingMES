SET XACT_ABORT ON;
BEGIN TRANSACTION;

ALTER TABLE dbo.LoggerEvent DROP CONSTRAINT CK_LoggerEvent_StartAfterStop;
ALTER TABLE dbo.LoggerEvent DROP CONSTRAINT CK_LoggerEvent_DurationMin_Positive;
ALTER TABLE dbo.LoggerEvent ALTER COLUMN StopDateTime datetime2(0) NULL;
ALTER TABLE dbo.LoggerEvent ALTER COLUMN StartDateTime datetime2(0) NULL;
ALTER TABLE dbo.LoggerEvent ALTER COLUMN DurationMin decimal(10,1) NOT NULL;
ALTER TABLE dbo.LoggerEvent ADD CONSTRAINT CK_LoggerEvent_StartAfterStop
	CHECK ((StopDateTime IS NULL AND StartDateTime IS NULL)
		OR (StopDateTime IS NOT NULL AND StartDateTime IS NOT NULL
			AND StartDateTime > StopDateTime));
ALTER TABLE dbo.LoggerEvent ADD CONSTRAINT CK_LoggerEvent_DurationMin_Positive
	CHECK (DurationMin > 0);

COMMIT TRANSACTION;