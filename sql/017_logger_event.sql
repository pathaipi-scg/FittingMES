SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.LoggerEvent', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.LoggerEvent
    (
        LoggerEventID bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_LoggerEvent PRIMARY KEY,
        ProductionDate date NOT NULL,
        StopDateTime datetime2(0) NOT NULL,
        StartDateTime datetime2(0) NOT NULL,
        DurationMin int NOT NULL,
        McId int NOT NULL,
        McInstanceNo int NOT NULL,
        RelatedMcId int NULL,
        RelatedMcInstanceNo int NULL,
        SubMcId int NULL,
        SubMcInstanceNo int NULL,
        StopId int NOT NULL,
        SubStopId int NULL,
        CauseId int NULL,
        MEO char(1) NULL,
        MachineNameSnapshot nvarchar(100) NOT NULL,
        RelatedMachineSnapshot nvarchar(100) NULL,
        SubMachineSnapshot nvarchar(100) NULL,
        StopTypeSnapshot nvarchar(100) NOT NULL,
        SubStopTypeSnapshot nvarchar(100) NULL,
        CauseSnapshot nvarchar(500) NULL,
        Note nvarchar(1000) NULL,
        SourceType varchar(20) NOT NULL
            CONSTRAINT DF_LoggerEvent_SourceType DEFAULT ('MANUAL'),
        ClassificationSource varchar(20) NOT NULL,
        CreatedAt datetime2(3) NOT NULL
            CONSTRAINT DF_LoggerEvent_CreatedAt DEFAULT (SYSDATETIME()),
        CreatedBy nvarchar(200) NULL,

        CONSTRAINT CK_LoggerEvent_DurationMin_Positive
            CHECK (DurationMin > 0),
        CONSTRAINT CK_LoggerEvent_McInstanceNo_Positive
            CHECK (McInstanceNo > 0),
        CONSTRAINT CK_LoggerEvent_RelatedMachine_InstancePair
            CHECK ((RelatedMcId IS NULL AND RelatedMcInstanceNo IS NULL)
                OR (RelatedMcId IS NOT NULL AND RelatedMcInstanceNo IS NOT NULL
                    AND RelatedMcInstanceNo > 0)),
        CONSTRAINT CK_LoggerEvent_SubMachine_InstancePair
            CHECK ((SubMcId IS NULL AND SubMcInstanceNo IS NULL)
                OR (SubMcId IS NOT NULL AND SubMcInstanceNo IS NOT NULL
                    AND SubMcInstanceNo > 0)),
        CONSTRAINT CK_LoggerEvent_MEO
            CHECK (MEO IS NULL OR MEO IN ('M', 'E', 'O')),
        CONSTRAINT CK_LoggerEvent_SourceType
            CHECK (SourceType IN ('MANUAL', 'PLC', 'SYSTEM')),
        CONSTRAINT CK_LoggerEvent_ClassificationSource
            CHECK (ClassificationSource IN
                ('CAUSE_SHORTCUT', 'MANUAL', 'DURATION_RULE')),
        CONSTRAINT CK_LoggerEvent_StartAfterStop
            CHECK (StartDateTime > StopDateTime)
    );

    ALTER TABLE dbo.LoggerEvent
        ADD CONSTRAINT FK_LoggerEvent_Mc
            FOREIGN KEY (McId)
            REFERENCES dbo.Fitting_MainMachine (McId),
        CONSTRAINT FK_LoggerEvent_RelatedMc
            FOREIGN KEY (RelatedMcId)
            REFERENCES dbo.Fitting_MainMachine (McId),
        CONSTRAINT FK_LoggerEvent_SubMc
            FOREIGN KEY (SubMcId)
            REFERENCES dbo.Fitting_SubMachine (SubMcId),
        CONSTRAINT FK_LoggerEvent_Stop
            FOREIGN KEY (StopId)
            REFERENCES dbo.Fitting_StopType (StopId),
        CONSTRAINT FK_LoggerEvent_SubStop
            FOREIGN KEY (SubStopId)
            REFERENCES dbo.Fitting_SubStopType (SubStopId),
        CONSTRAINT FK_LoggerEvent_Cause
            FOREIGN KEY (CauseId)
            REFERENCES dbo.Fitting_Cause (CauseId);

    CREATE INDEX IX_LoggerEvent_ProductionDate_Stop
        ON dbo.LoggerEvent (ProductionDate, StopDateTime, LoggerEventID);

    CREATE INDEX IX_LoggerEvent_Machine
        ON dbo.LoggerEvent (McId, McInstanceNo, StopDateTime);

    CREATE INDEX IX_LoggerEvent_RelatedMachine
        ON dbo.LoggerEvent (RelatedMcId, RelatedMcInstanceNo, StopDateTime)
        WHERE RelatedMcId IS NOT NULL;

    CREATE INDEX IX_LoggerEvent_Cause
        ON dbo.LoggerEvent (CauseId, StopDateTime)
        WHERE CauseId IS NOT NULL;
END;

COMMIT TRANSACTION;
GO
