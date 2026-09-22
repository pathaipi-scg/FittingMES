-- Unicode-only repair of Special Ridge ProductName; no schema or identity changes.
SET XACT_ABORT ON;
BEGIN TRANSACTION;
UPDATE dbo.ProductCodeMaster SET ProductName = N'ปิดจั่ว'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '01';
UPDATE dbo.ProductCodeMaster SET ProductName = N'ปิดชาย'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '02';
UPDATE dbo.ProductCodeMaster SET ProductName = N'หางมน'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '03';
UPDATE dbo.ProductCodeMaster SET ProductName = N'2 ทาง'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '04';
UPDATE dbo.ProductCodeMaster SET ProductName = N'3 ทาง'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '05';
UPDATE dbo.ProductCodeMaster SET ProductName = N'4 ทาง'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '06';
UPDATE dbo.ProductCodeMaster SET ProductName = N'ข้างผนัง'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '07';
UPDATE dbo.ProductCodeMaster SET ProductName = N'โค้งผนัง E'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '08';
UPDATE dbo.ProductCodeMaster SET ProductName = N'โค้งผนัง C'
WHERE ProductFamily = 'Special Ridge' AND ProductCode = '09';
COMMIT TRANSACTION;
