/****** Script for SelectTopNRows command from SSMS  ******/
SELECT 
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[LotProdID]
	  ,[RawMat]
      ,CASE WHEN [RawMat]='WGH1' THEN CAST(Sand*pWGH1/100 AS DECIMAL(10,1)) ELSE 
	   CASE WHEN [RawMat]='WGH2' THEN CAST(Sand*pWGH2/100 AS DECIMAL(10,1)) ELSE 
	   CASE WHEN [RawMat]='WGH3' THEN CAST(Sand*pWGH3/100 AS DECIMAL(10,1)) ELSE 
	   CASE WHEN [RawMat]='WGH4' THEN CAST(Sand*pWGH4/100 AS DECIMAL(10,1)) ELSE qty END END END END AS qty
      --,[qty]
      ,[avg]
      ,[cnt]
	  ,[Sand]
	  ,[pWGH1]
	  ,[pWGH2]
	  ,[pWGH3]
	  ,[pWGH4]
FROM(
SELECT 
       T1.[dt]
      ,T1.[RecTime]
      ,T1.[fdt]
      ,T1.[mTime]
      ,[RawMat]
      ,T1.[LotProdID]
      ,[qty]
      ,[avg]
      ,[cnt]
	  ,[Sand]
	  ,[pWGH1]
	  ,[pWGH2]
	  ,[pWGH3]
	  ,[pWGH4]
FROM(
SELECT 
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[RawMat]
      ,[LotProdID]
      ,[qty]
      ,[avg]
      ,[cnt]
  FROM [UsageToAngel_ByLot] 
  where RawMat not like '%CHG%'
) AS T1 left outer join UsageToAngel_pWghByLot
on T1.LotProdID = UsageToAngel_pWghByLot.LotProdID
) AS T2
where RawMat not like 'avgWGH%'
and   RawMat not like 'pWGH%'
and   RawMat not like 'speedWGH%'
and   RawMat not like 'PvPugBoxLevel%'
and   RawMat not like 'PvPugBuffer%'
and   RawMat not like 'avgMmoist%'
and   RawMat not like 'avgSmoist%'
and   RawMat not like 'MortarMoist%'
and   RawMat not like 'SandMoist%'
and   RawMat not like '%Fml'
and   RawMat not like '%FML'
and   RawMat not like '%SP'
and   RawMat not like '%SetP'
and   RawMat not like '%PV'
and   RawMat not like '%BatchCount'
and   RawMat not like '%BatchCnt'
and   RawMat not like '%Water%'
order by RecTime DESC