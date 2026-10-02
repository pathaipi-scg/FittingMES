SET XACT_ABORT ON;
BEGIN TRANSACTION;

INSERT INTO dbo.MaterialUsageMaster
    (MaterialUsageCode, MaterialNameTH, MaterialNameEN, Unit, SortOrder,
     UsageType, IsActive, APIFieldCode)
SELECT v.MaterialUsageCode, v.MaterialNameTH, v.MaterialNameEN, v.Unit, v.SortOrder,
       v.UsageType, v.IsActive, v.APIFieldCode
FROM (VALUES
    ('calcium',   'Calcium',    'Calcium',    'kg', 55, 'MATERIAL', 1, NULL),
    ('palletOil', 'Pallet Oil', 'Pallet Oil', 'L',  71, 'MATERIAL', 1, NULL),
    ('ft30',      'FT30',       'FT30',       'L',  72, 'MATERIAL', 1, NULL),
    ('bl',        'BL',         'BL',         'L',  73, 'MATERIAL', 1, NULL)
) AS v(MaterialUsageCode, MaterialNameTH, MaterialNameEN, Unit, SortOrder,
       UsageType, IsActive, APIFieldCode)
WHERE NOT EXISTS (
    SELECT 1
    FROM dbo.MaterialUsageMaster m
    WHERE m.MaterialUsageCode = v.MaterialUsageCode
);

COMMIT TRANSACTION;
