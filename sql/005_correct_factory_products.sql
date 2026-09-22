-- Exact factory-reference correction; only these family/code master rows are affected.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
DECLARE @Products TABLE(ProductFamily varchar(30),ProductCode varchar(2),ProductName nvarchar(100));
INSERT INTO @Products VALUES
('Special Ridge','01',N'ปิดจั่ว'),
('Special Ridge','02',N'ปิดชาย'),
('Special Ridge','03',N'หางมน'),
('Special Ridge','04',N'2 ทาง'),
('Special Ridge','05',N'3 ทาง'),
('Special Ridge','06',N'4 ทาง'),
('Special Ridge','07',N'ข้างผนัง'),
('Special Ridge','08',N'โค้งผนัง E'),
('Special Ridge','09',N'โค้งผนัง C'),
('Prestige Common','11',N'Angle Ridge'),
('Prestige Common','12',N'Angle Ridge End'),
('Prestige Common','13',N'Angle HIP'),
('Prestige Common','14',N'Angle HIP End'),
('Prestige Common','15',N'Verge Seamless'),
('Prestige Common','16',N'Verge Seamless End'),
('Prestige Common','17',N'Wall Ridge'),
('Prestige Common','18',N'Wall Verge'),
('Prestige Common','19',N'Verge'),
('Prestige Common','20',N'Verge End');
UPDATE target SET ProductName=source.ProductName
FROM dbo.ProductCodeMaster target
JOIN @Products source ON target.ProductFamily=source.ProductFamily AND target.ProductCode=source.ProductCode
WHERE target.ProductName COLLATE Latin1_General_100_BIN2 <> source.ProductName COLLATE Latin1_General_100_BIN2;
INSERT INTO dbo.ProductCodeMaster(ProductFamily,ProductCode,ProductGroup,ProductName,IsActive)
SELECT source.ProductFamily,source.ProductCode,source.ProductFamily,source.ProductName,1
FROM @Products source
WHERE NOT EXISTS(SELECT 1 FROM dbo.ProductCodeMaster target WITH (UPDLOCK,HOLDLOCK)
    WHERE target.ProductFamily=source.ProductFamily AND target.ProductCode=source.ProductCode);
COMMIT TRANSACTION;
