-- Confirmed factory reference. Inserts only; never alters existing products or mappings.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
DECLARE @Products TABLE (ProductFamily varchar(30),ProductCode varchar(2),ProductName nvarchar(100));
INSERT INTO @Products VALUES
(N'Special Ridge', '01', N'ปิดจั่ว'),
(N'Special Ridge', '02', N'ปิดชาย'),
(N'Special Ridge', '03', N'หางมน'),
(N'Special Ridge', '04', N'2 ทาง'),
(N'Special Ridge', '05', N'3 ทาง'),
(N'Special Ridge', '06', N'4 ทาง'),
(N'Special Ridge', '07', N'ข้างผนัง'),
(N'Special Ridge', '08', N'โค้งผนัง E'),
(N'Special Ridge', '09', N'โค้งผนัง C'),
(N'Prestige Common', '11', N'Angle Ridge'),
(N'Prestige Common', '12', N'Angle Ridge End'),
(N'Prestige Common', '13', N'Angle HIP'),
(N'Prestige Common', '14', N'Angle HIP End'),
(N'Prestige Common', '15', N'Verge Seamless'),
(N'Prestige Common', '16', N'Verge Seamless End'),
(N'Prestige Common', '17', N'Wall Ridge'),
(N'Prestige Common', '18', N'Wall Verge'),
(N'Prestige Common', '19', N'Verge');
IF EXISTS (
    SELECT 1 FROM @Products source
    JOIN dbo.ProductCodeMaster target WITH (UPDLOCK,HOLDLOCK)
      ON target.ProductFamily=source.ProductFamily AND target.ProductCode=source.ProductCode
    WHERE target.ProductName COLLATE Latin1_General_100_BIN2 <> source.ProductName COLLATE Latin1_General_100_BIN2
       OR target.IsActive<>1
)
    THROW 51000, 'Existing factory product conflicts with confirmed reference; no rows changed.', 1;
INSERT INTO dbo.ProductCodeMaster
    (ProductFamily,ProductCode,ProductGroup,ProductName,IsActive)
SELECT source.ProductFamily,source.ProductCode,source.ProductFamily,source.ProductName,1
FROM @Products source
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.ProductCodeMaster target WITH (UPDLOCK,HOLDLOCK)
    WHERE target.ProductFamily=source.ProductFamily AND target.ProductCode=source.ProductCode
);
COMMIT TRANSACTION;
