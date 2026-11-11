SET NOCOUNT ON;

IF DB_NAME() <> N'SB23'
   AND NOT (
       DB_NAME() = N'SB23_TEST'
       AND CONVERT(nvarchar(10), SESSION_CONTEXT(N'FittingMES_029_TestRun')) = N'1'
   )
    THROW 52900, 'Preflight 029 is intended for SB23 or an authorized SB23_TEST session.', 1;

IF OBJECT_ID(N'dbo.PressProduction', N'U') IS NULL
   OR OBJECT_ID(N'dbo.ProductionLot', N'U') IS NULL
    THROW 52901, 'A required Press Production or Production Lot table is missing.', 1;

SELECT
    pp.ProductionID,
    pp.MachineCode,
    pp.ShiftMasterID,
    COUNT_BIG(*) AS ActiveIdentityCount
FROM dbo.PressProduction AS pp
WHERE pp.ReleasedAt IS NULL
  AND pp.ShiftMasterID IS NOT NULL
GROUP BY pp.ProductionID, pp.MachineCode, pp.ShiftMasterID
HAVING COUNT_BIG(*) > 1
ORDER BY pp.ProductionID, pp.MachineCode, pp.ShiftMasterID;

SELECT
    first_assignment.PressProductionID AS FirstPressProductionID,
    first_lot.LotNo AS FirstLotNo,
    first_lot.ProdDate AS ProductionDate,
    first_assignment.MachineCode AS FirstMachineCode,
    first_assignment.MouldID AS FirstMouldID,
    first_assignment.ProductionStartTime AS FirstStartTime,
    first_assignment.ProductionEndTime AS FirstEndTime,
    second_assignment.PressProductionID AS SecondPressProductionID,
    second_lot.LotNo AS SecondLotNo,
    second_assignment.MachineCode AS SecondMachineCode,
    second_assignment.MouldID AS SecondMouldID,
    second_assignment.ProductionStartTime AS SecondStartTime,
    second_assignment.ProductionEndTime AS SecondEndTime
FROM dbo.PressProduction AS first_assignment
JOIN dbo.ProductionLot AS first_lot
  ON first_lot.ProductionID = first_assignment.ProductionID
JOIN dbo.PressProduction AS second_assignment
  ON second_assignment.PressProductionID > first_assignment.PressProductionID
JOIN dbo.ProductionLot AS second_lot
  ON second_lot.ProductionID = second_assignment.ProductionID
WHERE first_lot.IsActive = 1
  AND second_lot.IsActive = 1
  AND first_assignment.ReleasedAt IS NULL
  AND second_assignment.ReleasedAt IS NULL
  AND (first_assignment.MachineCode = second_assignment.MachineCode
       OR (first_assignment.MouldID IS NOT NULL
           AND first_assignment.MouldID = second_assignment.MouldID))
  AND (
      first_assignment.ProductionStartTime IS NULL
      OR second_assignment.ProductionStartTime IS NULL
      OR (first_assignment.ProductionEndTime IS NOT NULL
          AND first_assignment.ProductionEndTime <= first_assignment.ProductionStartTime)
      OR (second_assignment.ProductionEndTime IS NOT NULL
          AND second_assignment.ProductionEndTime <= second_assignment.ProductionStartTime)
      OR ((first_assignment.ProductionEndTime IS NULL
           OR second_assignment.ProductionStartTime < first_assignment.ProductionEndTime)
          AND (second_assignment.ProductionEndTime IS NULL
               OR first_assignment.ProductionStartTime < second_assignment.ProductionEndTime))
  )
ORDER BY first_lot.ProdDate, first_assignment.PressProductionID,
         second_assignment.PressProductionID;

SELECT
    pp.PressProductionID,
    lot.LotNo,
    lot.ProdDate AS ProductionDate,
    pp.MachineCode,
    pp.MouldID,
    pp.ProductionStartTime,
    pp.ProductionEndTime
FROM dbo.PressProduction AS pp
JOIN dbo.ProductionLot AS lot
  ON lot.ProductionID = pp.ProductionID
WHERE lot.IsActive = 1
  AND pp.ReleasedAt IS NULL
  AND (pp.ProductionStartTime IS NULL
       OR (pp.ProductionEndTime IS NOT NULL
           AND pp.ProductionEndTime <= pp.ProductionStartTime))
ORDER BY lot.ProdDate, pp.PressProductionID;

SELECT
    i.name AS IndexName,
    i.is_unique AS IsUnique,
    i.filter_definition AS FilterDefinition,
    c.name AS KeyColumn,
    ic.key_ordinal AS KeyOrdinal
FROM sys.indexes AS i
JOIN sys.index_columns AS ic
  ON ic.object_id = i.object_id
 AND ic.index_id = i.index_id
JOIN sys.columns AS c
  ON c.object_id = ic.object_id
 AND c.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID(N'dbo.PressProduction')
  AND i.name = N'UX_PressProduction_Production_Machine_ShiftActive'
ORDER BY ic.key_ordinal;
