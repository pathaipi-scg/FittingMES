SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF OBJECT_ID(N'dbo.EquipmentMaster', N'U') IS NULL
        THROW 52400, 'Required dbo.EquipmentMaster table is missing.', 1;
    IF OBJECT_ID(N'dbo.ProductFamilyMaster', N'U') IS NULL
        THROW 52401, 'Required dbo.ProductFamilyMaster table is missing.', 1;
    IF OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
        THROW 52402, 'Required dbo.ProductionLot table is missing.', 1;
    IF COL_LENGTH(N'dbo.EquipmentMaster', N'EquipmentCode') IS NULL
       OR COL_LENGTH(N'dbo.ProductFamilyMaster', N'ProductFamilyID') IS NULL
       OR COL_LENGTH(N'dbo.ProductFamilyMaster', N'ProductFamily') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'ProductionID') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'ProdDate') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'Shift') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'ProductFamilyID') IS NULL
       OR COL_LENGTH(N'dbo.ProductionLot', N'IsActive') IS NULL
        THROW 52403, 'A required existing REJECT prerequisite column is missing.', 1;

    IF EXISTS (
        SELECT 1
        FROM sys.indexes i
        WHERE i.object_id=OBJECT_ID(N'dbo.EquipmentMaster')
          AND i.is_primary_key=1
          AND NOT EXISTS (
              SELECT 1
              FROM sys.index_columns ic
              JOIN sys.columns c
                ON c.object_id=ic.object_id AND c.column_id=ic.column_id
              WHERE ic.object_id=i.object_id
                AND ic.index_id=i.index_id
                AND ic.key_ordinal=1
                AND c.name=N'EquipmentCode'
          )
    ) OR NOT EXISTS (
        SELECT 1
        FROM sys.indexes i
        JOIN sys.index_columns ic
          ON ic.object_id=i.object_id AND ic.index_id=i.index_id
        JOIN sys.columns c
          ON c.object_id=ic.object_id AND c.column_id=ic.column_id
        WHERE i.object_id=OBJECT_ID(N'dbo.EquipmentMaster')
          AND i.is_primary_key=1
          AND ic.key_ordinal=1
          AND c.name=N'EquipmentCode'
          AND NOT EXISTS (
              SELECT 1
              FROM sys.index_columns extra
              WHERE extra.object_id=i.object_id
                AND extra.index_id=i.index_id
                AND extra.key_ordinal>1
          )
    )
        THROW 52404, 'EquipmentMaster primary key is not the expected EquipmentCode key.', 1;

    IF COL_LENGTH(N'dbo.EquipmentMaster', N'id') IS NOT NULL
        THROW 52405, 'EquipmentMaster.id already exists; migration will not reuse or replace it.', 1;

    IF OBJECT_ID(N'dbo.ShiftMaster', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.RejectCatalog', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.RejectSourceScope', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.RejectReason', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.RejectReasonProductFamily', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.ProductionRejectEntry', N'U') IS NOT NULL
       OR OBJECT_ID(N'dbo.DepalletRejectEntry', N'U') IS NOT NULL
        THROW 52406, 'At least one REJECT target table already exists; migration refused.', 1;

    ALTER TABLE dbo.EquipmentMaster
        ADD id bigint IDENTITY(1,1) NOT NULL;

    ALTER TABLE dbo.EquipmentMaster
        ADD CONSTRAINT UQ_EquipmentMaster_id UNIQUE (id);

    CREATE TABLE dbo.ShiftMaster
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_ShiftMaster PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_ShiftMaster_Rectime DEFAULT (GETDATE()),
        ShiftCode varchar(10) NOT NULL,
        ShiftName nvarchar(100) NOT NULL,
        IsActive bit NOT NULL
            CONSTRAINT DF_ShiftMaster_IsActive DEFAULT (1),
        CONSTRAINT UQ_ShiftMaster_ShiftCode UNIQUE (ShiftCode)
    );

    CREATE TABLE dbo.RejectCatalog
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_RejectCatalog PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_RejectCatalog_Rectime DEFAULT (GETDATE()),
        CatalogCode varchar(3) NOT NULL,
        CatalogName nvarchar(200) NOT NULL,
        IsActive bit NOT NULL
            CONSTRAINT DF_RejectCatalog_IsActive DEFAULT (1),
        CONSTRAINT UQ_RejectCatalog_CatalogCode UNIQUE (CatalogCode),
        CONSTRAINT CK_RejectCatalog_CatalogCode
            CHECK (CatalogCode IN ('R1','R2','R3'))
    );

    CREATE TABLE dbo.RejectSourceScope
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_RejectSourceScope PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_RejectSourceScope_Rectime DEFAULT (GETDATE()),
        SourceScopeCode varchar(10) NOT NULL,
        SourceScopeName nvarchar(100) NOT NULL,
        IsActive bit NOT NULL
            CONSTRAINT DF_RejectSourceScope_IsActive DEFAULT (1),
        CONSTRAINT UQ_RejectSourceScope_SourceScopeCode UNIQUE (SourceScopeCode),
        CONSTRAINT CK_RejectSourceScope_SourceScopeCode
            CHECK (SourceScopeCode IN ('PRESS','LINE'))
    );

    CREATE TABLE dbo.RejectReason
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_RejectReason PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_RejectReason_Rectime DEFAULT (GETDATE()),
        ReasonCode varchar(10) NOT NULL,
        RejectCatalogID bigint NOT NULL,
        ReasonNameTH nvarchar(400) NOT NULL,
        SortOrder int NOT NULL,
        RejectSourceScopeID bigint NOT NULL,
        IsOther bit NOT NULL
            CONSTRAINT DF_RejectReason_IsOther DEFAULT (0),
        IsActive bit NOT NULL
            CONSTRAINT DF_RejectReason_IsActive DEFAULT (1),
        CONSTRAINT UQ_RejectReason_ReasonCode UNIQUE (ReasonCode),
        CONSTRAINT UQ_RejectReason_CatalogSort UNIQUE (RejectCatalogID,SortOrder),
        CONSTRAINT FK_RejectReason_RejectCatalog
            FOREIGN KEY (RejectCatalogID) REFERENCES dbo.RejectCatalog(id),
        CONSTRAINT FK_RejectReason_SourceScope
            FOREIGN KEY (RejectSourceScopeID) REFERENCES dbo.RejectSourceScope(id)
    );

    CREATE TABLE dbo.RejectReasonProductFamily
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_RejectReasonProductFamily PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_RejectReasonProductFamily_Rectime DEFAULT (GETDATE()),
        RejectReasonID bigint NOT NULL,
        ProductFamilyID int NOT NULL,
        CONSTRAINT UQ_RejectReasonProductFamily_ReasonFamily
            UNIQUE (RejectReasonID,ProductFamilyID),
        CONSTRAINT FK_RejectReasonProductFamily_Reason
            FOREIGN KEY (RejectReasonID) REFERENCES dbo.RejectReason(id),
        CONSTRAINT FK_RejectReasonProductFamily_Family
            FOREIGN KEY (ProductFamilyID) REFERENCES dbo.ProductFamilyMaster(ProductFamilyID)
    );

    CREATE TABLE dbo.ProductionRejectEntry
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_ProductionRejectEntry PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_ProductionRejectEntry_Rectime DEFAULT (GETDATE()),
        ProductionDate date NOT NULL,
        ShiftID bigint NOT NULL,
        LineEquipmentID bigint NOT NULL,
        SourceEquipmentID bigint NOT NULL,
        RejectSourceScopeID bigint NOT NULL,
        ProductionID bigint NOT NULL,
        RejectReasonID bigint NOT NULL,
        Qty int NOT NULL,
        CONSTRAINT CK_ProductionRejectEntry_Qty CHECK (Qty > 0),
        CONSTRAINT FK_ProductionRejectEntry_Shift
            FOREIGN KEY (ShiftID) REFERENCES dbo.ShiftMaster(id),
        CONSTRAINT FK_ProductionRejectEntry_LineEquipment
            FOREIGN KEY (LineEquipmentID) REFERENCES dbo.EquipmentMaster(id),
        CONSTRAINT FK_ProductionRejectEntry_SourceEquipment
            FOREIGN KEY (SourceEquipmentID) REFERENCES dbo.EquipmentMaster(id),
        CONSTRAINT FK_ProductionRejectEntry_SourceScope
            FOREIGN KEY (RejectSourceScopeID) REFERENCES dbo.RejectSourceScope(id),
        CONSTRAINT FK_ProductionRejectEntry_ProductionLot
            FOREIGN KEY (ProductionID) REFERENCES dbo.ProductionLot(ProductionID),
        CONSTRAINT FK_ProductionRejectEntry_Reason
            FOREIGN KEY (RejectReasonID) REFERENCES dbo.RejectReason(id)
    );

    CREATE TABLE dbo.DepalletRejectEntry
    (
        id bigint IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_DepalletRejectEntry PRIMARY KEY,
        Rectime datetime NOT NULL
            CONSTRAINT DF_DepalletRejectEntry_Rectime DEFAULT (GETDATE()),
        ProductionDate date NOT NULL,
        ShiftID bigint NOT NULL,
        LineEquipmentID bigint NOT NULL,
        SourceEquipmentID bigint NOT NULL,
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

    INSERT INTO dbo.ShiftMaster (ShiftCode,ShiftName,IsActive)
    VALUES ('1',N'Shift 1',1),('2',N'Shift 2',1);

    INSERT INTO dbo.RejectCatalog (CatalogCode,CatalogName,IsActive)
    VALUES
        ('R1',N'Special Ridge',1),
        ('R2',N'Prestige',1),
        ('R3',N'NeuFit / NeuStile + Oriental',1);

    INSERT INTO dbo.RejectSourceScope (SourceScopeCode,SourceScopeName,IsActive)
    VALUES ('PRESS',N'PRESS',1),('LINE',N'LINE',1);

    DECLARE @ReasonSeed table
    (
        CatalogCode varchar(3) NOT NULL,
        ReasonCode varchar(10) NOT NULL,
        ReasonNameTH nvarchar(400) NOT NULL,
        SourceScopeCode varchar(10) NOT NULL,
        IsOther bit NOT NULL
    );

    -- This seed is transcribed from the complete approved matrix in
    -- md/REJECT_MODULE_REQUIREMENTS.md; catalog and scope are explicit.
    INSERT INTO @ReasonSeed
        (CatalogCode,ReasonCode,ReasonNameTH,SourceScopeCode,IsOther)
    VALUES
        ('R1','R101',N'เนื้อแหว่งใต้ครอบ','PRESS',0),
        ('R1','R102',N'ครอบแตกบิ่น','PRESS',0),
        ('R1','R103',N'ขอบแหว่ง','PRESS',0),
        ('R1','R104',N'ครอบมีรอยขีด','PRESS',0),
        ('R1','R105',N'ผิวปูดบวม','PRESS',0),
        ('R1','R106',N'ร้าวแก้มครอบ','PRESS',0),
        ('R1','R107',N'ร้าวใต้ครอบ','PRESS',0),
        ('R1','R108',N'ร้าวคอครอบ','PRESS',0),
        ('R1','R109',N'ร้าวจานครอบ','PRESS',0),
        ('R1','R110',N'ร้าวทะลุตัวครอบ','PRESS',0),
        ('R1','R111',N'ร้าวท้ายครอบ','PRESS',0),
        ('R1','R112',N'ร้าวผิวครอบ','PRESS',0),
        ('R1','R113',N'ร้าวหัวครอบ','PRESS',0),
        ('R1','R114',N'สีเป็นเม็ด','LINE',0),
        ('R1','R115',N'สีเป็นฟอง','LINE',0),
        ('R1','R116',N'สี Salary ไม่เต็ม','LINE',0),
        ('R1','R117',N'สีด้าน','LINE',0),
        ('R1','R118',N'ปูนติดโมล','PRESS',0),
        ('R1','R119',N'สีถลอก','LINE',0),
        ('R1','R120',N'สีปูด','LINE',0),
        ('R1','R121',N'สีหยด','LINE',0),
        ('R1','R122',N'สีไหล/ เยิ้ม','LINE',0),
        ('R1','R123',N'สีพอง','LINE',0),
        ('R1','R124',N'แกะงานแตก','LINE',0),
        ('R1','R125',N'หัวครอบแตก','PRESS',0),
        ('R1','R126',N'รถยกชนแตก','LINE',0),
        ('R1','R127',N'ยกชน Rack','LINE',0),
        ('R1','R199',N'อื่นๆ','LINE',1),
        ('R2','R201',N'ร้าวผิวตัวกระเบื้อง','PRESS',0),
        ('R2','R202',N'ร้าวรางลิ้นหงาย','PRESS',0),
        ('R2','R203',N'ร้าวล่างรางลิ้นคว่ำ','PRESS',0),
        ('R2','R204',N'ร้าวล่างตัวครอบ','PRESS',0),
        ('R2','R205',N'ร้าวชายกระเบื้อง','PRESS',0),
        ('R2','R206',N'ร้าวเขื่อนรางลิ้นหงาย','PRESS',0),
        ('R2','R207',N'ร้าวเขื่อนรางลิ้นคว่ำ','PRESS',0),
        ('R2','R208',N'บิ่นแหว่ง','PRESS',0),
        ('R2','R209',N'ผิวครอบปูดบวม','PRESS',0),
        ('R2','R210',N'ผิวครอบไม่เรียบ','PRESS',0),
        ('R2','R211',N'ขอบไม่คม / ขอบไม่เรียบ','PRESS',0),
        ('R2','R212',N'รูพรุน','PRESS',0),
        ('R2','R213',N'แตกรูตะปู','PRESS',0),
        ('R2','R214',N'ผ้าขาด/ติดผ้า/เนื้อแหว่งใต้ครอบ','PRESS',0),
        ('R2','R215',N'ปูนติดโมล','PRESS',0),
        ('R2','R216',N'สี Salary ไม่เต็ม','LINE',0),
        ('R2','R217',N'สีเป็นเม็ด','LINE',0),
        ('R2','R218',N'สีพอง','LINE',0),
        ('R2','R219',N'สีหนา','LINE',0),
        ('R2','R220',N'สีไหล/ เยิ้ม','LINE',0),
        ('R2','R221',N'สีหยด','LINE',0),
        ('R2','R222',N'สีปูด','LINE',0),
        ('R2','R223',N'ครอบบาง/น้ำหนักเบา','PRESS',0),
        ('R2','R224',N'ยกชน Rack','LINE',0),
        ('R2','R225',N'รถยกชน','LINE',0),
        ('R2','R299',N'อื่นๆ','LINE',1),
        ('R3','R301',N'ร้าวผิวตัวกระเบื้อง','PRESS',0),
        ('R3','R302',N'ร้าวอกรับน้ำ','PRESS',0),
        ('R3','R303',N'ร้าวสันเขื่อน','PRESS',0),
        ('R3','R304',N'เป็นครีบ','PRESS',0),
        ('R3','R305',N'คราบน้ำ','PRESS',0),
        ('R3','R306',N'ร้าวรางลิ้นหงาย','PRESS',0),
        ('R3','R307',N'ร้าวชายกระเบื้อง','PRESS',0),
        ('R3','R308',N'ร้าวล่างรางลิ้นคว่ำ','PRESS',0),
        ('R3','R309',N'ร้าวขอเกาะ','PRESS',0),
        ('R3','R310',N'ร้าวล่างตัวครอบ','PRESS',0),
        ('R3','R311',N'บิ่นแหว่ง / แตกบิ่น','PRESS',0),
        ('R3','R312',N'ปูนติดโมลบน','PRESS',0),
        ('R3','R313',N'โก่งแอ่น','PRESS',0),
        ('R3','R314',N'รูพรุน','PRESS',0),
        ('R3','R315',N'ผิวปูดบวม/ผิวระเบิด','PRESS',0),
        ('R3','R316',N'ขอบไม่คม','PRESS',0),
        ('R3','R317',N'แต่งผิวไม่เรียบ','PRESS',0),
        ('R3','R318',N'แตกรูตะปู','PRESS',0),
        ('R3','R319',N'แบบชนในไลน์ผลิต','LINE',0),
        ('R3','R320',N'สีไม่เต็มแผ่น','LINE',0),
        ('R3','R321',N'สีนอง / สีแตก','LINE',0),
        ('R3','R322',N'เนื้อแหว่งใต้ครอบ','PRESS',0),
        ('R3','R323',N'กระเบื้อง / ครอบแฉะ','PRESS',0),
        ('R3','R399',N'อื่นๆ','LINE',1);

    IF (SELECT COUNT(*) FROM @ReasonSeed) <> 78
        THROW 52407, 'Canonical REJECT reason seed count is not 78.', 1;
    IF EXISTS (
        SELECT ReasonCode
        FROM @ReasonSeed
        GROUP BY ReasonCode
        HAVING COUNT(*) <> 1
    )
        THROW 52408, 'Duplicate ReasonCode found in the REJECT seed.', 1;
    IF EXISTS (
        SELECT 1
        FROM (SELECT DISTINCT CatalogCode FROM @ReasonSeed) s
        LEFT JOIN dbo.RejectCatalog c ON c.CatalogCode=s.CatalogCode
        GROUP BY s.CatalogCode
        HAVING COUNT(c.id) <> 1
    ) OR EXISTS (
        SELECT 1
        FROM (SELECT DISTINCT SourceScopeCode FROM @ReasonSeed) s
        LEFT JOIN dbo.RejectSourceScope sc ON sc.SourceScopeCode=s.SourceScopeCode
        GROUP BY s.SourceScopeCode
        HAVING COUNT(sc.id) <> 1
    )
        THROW 52409, 'A reason seed catalog or SourceScope code did not resolve exactly once.', 1;
    IF NOT EXISTS (
        SELECT 1 FROM @ReasonSeed WHERE ReasonCode='R319' AND SourceScopeCode='LINE'
    )
       OR (SELECT COUNT(*) FROM @ReasonSeed WHERE ReasonCode='R319') <> 1
        THROW 52410, 'R319 must resolve exactly once to LINE.', 1;
    IF EXISTS (
        SELECT 1 FROM @ReasonSeed
        WHERE ReasonCode IN ('R199','R299','R399') AND IsOther<>1
    ) OR (SELECT COUNT(*) FROM @ReasonSeed WHERE IsOther=1) <> 3
        THROW 52411, 'The three approved Other reasons must be explicitly classified.', 1;

    ;WITH OrderedReasonSeed AS
    (
        SELECT s.CatalogCode,s.ReasonCode,s.ReasonNameTH,s.SourceScopeCode,s.IsOther,
               ROW_NUMBER() OVER (PARTITION BY s.CatalogCode ORDER BY s.ReasonCode) AS SortOrder
        FROM @ReasonSeed s
    )
    INSERT INTO dbo.RejectReason
        (ReasonCode,RejectCatalogID,ReasonNameTH,SortOrder,RejectSourceScopeID,IsOther,IsActive)
    SELECT s.ReasonCode,c.id,s.ReasonNameTH,CONVERT(int,s.SortOrder),sc.id,s.IsOther,1
    FROM OrderedReasonSeed s
    JOIN dbo.RejectCatalog c ON c.CatalogCode=s.CatalogCode
    JOIN dbo.RejectSourceScope sc ON sc.SourceScopeCode=s.SourceScopeCode;

    DECLARE @FamilySeed table
    (
        CatalogCode varchar(3) NOT NULL,
        ProductFamily varchar(30) NOT NULL
    );

    INSERT INTO @FamilySeed (CatalogCode,ProductFamily)
    VALUES
        ('R1','Special Ridge'),
        ('R2','Prestige'),
        ('R3','NeuFit / NeuStile'),
        ('R3','Oriental');

    IF EXISTS (
        SELECT f.ProductFamily
        FROM @FamilySeed f
        LEFT JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamily=f.ProductFamily
        GROUP BY f.ProductFamily
        HAVING COUNT(pf.ProductFamilyID) <> 1
    )
        THROW 52412, 'An approved ProductFamily did not resolve exactly once.', 1;

    INSERT INTO dbo.RejectReasonProductFamily (RejectReasonID,ProductFamilyID)
    SELECT r.id,pf.ProductFamilyID
    FROM dbo.RejectReason r
    JOIN dbo.RejectCatalog c ON c.id=r.RejectCatalogID
    JOIN @FamilySeed f ON f.CatalogCode=c.CatalogCode
    JOIN dbo.ProductFamilyMaster pf ON pf.ProductFamily=f.ProductFamily;

    IF (SELECT COUNT(*) FROM dbo.RejectCatalog) <> 3
       OR (SELECT COUNT(*) FROM dbo.RejectSourceScope) <> 2
       OR (SELECT COUNT(*) FROM dbo.RejectReason) <> 78
       OR (SELECT COUNT(*) FROM dbo.RejectReasonProductFamily) <> 102
       OR (SELECT COUNT(*) FROM dbo.ShiftMaster) <> 2
        THROW 52413, 'Post-seed REJECT row counts do not match the approved catalog.', 1;

    CREATE INDEX IX_RejectReason_SourceCatalogActive
        ON dbo.RejectReason (RejectSourceScopeID,RejectCatalogID,IsActive)
        INCLUDE (ReasonCode,SortOrder);

    CREATE INDEX IX_RejectReasonProductFamily_Family
        ON dbo.RejectReasonProductFamily (ProductFamilyID,RejectReasonID);

    CREATE INDEX IX_ProductionRejectEntry_CAL
        ON dbo.ProductionRejectEntry (ProductionDate,ShiftID,ProductionID)
        INCLUDE (LineEquipmentID,SourceEquipmentID,RejectReasonID,RejectSourceScopeID,Qty);
    CREATE INDEX IX_ProductionRejectEntry_ProductionID
        ON dbo.ProductionRejectEntry (ProductionID);
    CREATE INDEX IX_ProductionRejectEntry_LineDate
        ON dbo.ProductionRejectEntry (LineEquipmentID,ProductionDate,ShiftID);
    CREATE INDEX IX_ProductionRejectEntry_SourceDate
        ON dbo.ProductionRejectEntry (SourceEquipmentID,ProductionDate,ShiftID);
    CREATE INDEX IX_ProductionRejectEntry_Reason
        ON dbo.ProductionRejectEntry (RejectReasonID);

    CREATE INDEX IX_DepalletRejectEntry_CAL
        ON dbo.DepalletRejectEntry (ProductionDate,ShiftID,ProductionID)
        INCLUDE (LineEquipmentID,SourceEquipmentID,RejectReasonID,RejectSourceScopeID,Qty);
    CREATE INDEX IX_DepalletRejectEntry_ProductionID
        ON dbo.DepalletRejectEntry (ProductionID);
    CREATE INDEX IX_DepalletRejectEntry_LineDate
        ON dbo.DepalletRejectEntry (LineEquipmentID,ProductionDate,ShiftID);
    CREATE INDEX IX_DepalletRejectEntry_SourceDate
        ON dbo.DepalletRejectEntry (SourceEquipmentID,ProductionDate,ShiftID);
    CREATE INDEX IX_DepalletRejectEntry_Reason
        ON dbo.DepalletRejectEntry (RejectReasonID);

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0
        ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
