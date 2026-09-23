/****** Script for SelectTopNRows command from SSMS  ******/
SELECT 
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[LotProdID]
	  ,[RawMat]
      ,[qty]
	  ,[avg] AS oavg
      ,CASE WHEN cnt > 0 THEN [qty]/[cnt] ELSE qty END AS [avg]
      ,[cnt]
	  ,[Sand]
	  ,[drySand]
	  ,[pWGH1]
	  ,[pWGH2]
	  ,[pWGH3]
	  ,[pWGH4]
	  ,T4.[PlanName]
	  ,[DateStr]
	  ,[MaterialCode]
      ,[NameThai]
      ,[Curve]
FROM(
SELECT 
       MAX([dt]       )  AS [dt]                     
      ,MAX([RecTime]  )  AS [RecTime]                    
      ,MAX([fdt]      )  AS [fdt]                    
      ,MAX([mTime]    )  AS [mTime]                  
      ,MAX([LotProdID])  AS [LotProdID]          
      ,MAX([PlanName] )  AS [PlanName]    
	  ,MAX([DateStr]  )  AS [DateStr]   
      ,MAX([RawMat]   )  AS [RawMat]                     
      ,SUM([qty]      )  AS [qty]                    
      ,AVG([avg]      )  AS [avg]                    
      ,SUM([cnt]      )  AS [cnt]                    
      ,MAX([Sand]     )  AS [Sand]                   
      ,MAX([drySand]  )  AS [drySand]                    
      ,MAX([pWGH1]    )  AS [pWGH1]                  
      ,MAX([pWGH2]    )  AS [pWGH2]                  
      ,MAX([pWGH3]    )  AS [pWGH3]                  
      ,MAX([pWGH4]    )  AS [pWGH4]                              
FROM(
SELECT 
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[LotProdID]
	  ,[PlanName]
	  ,[DateStr]
	  --,[RawMat]
	  ,CASE WHEN [RawMat]='clr1CementLog' THEN 'ClrCementLog' ELSE 
	   CASE WHEN [RawMat]='clr1SandLog'	  THEN 'ClrSandLog'   ELSE
	   CASE WHEN [RawMat]='clr2CementLog' THEN 'ClrCementLog' ELSE 
	   CASE WHEN [RawMat]='clr2SandLog'	  THEN 'ClrSandLog'   ELSE [RawMat] END END END END AS RawMat
      ,CASE WHEN [RawMat]='WGH1' THEN CAST(drySand*pWGH1/100 AS DECIMAL(10,1)) ELSE 
	   CASE WHEN [RawMat]='WGH2' THEN CAST(drySand*pWGH2/100 AS DECIMAL(10,1)) ELSE 
	   CASE WHEN [RawMat]='WGH3' THEN CAST(drySand*pWGH3/100 AS DECIMAL(10,1)) ELSE 
	   CASE WHEN [RawMat]='WGH4' THEN CAST(drySand*pWGH4/100 AS DECIMAL(10,1)) ELSE qty END END END END AS qty
      --,[qty]
      ,[avg]
      ,[cnt]
	  ,[Sand]
	  ,[drySand]
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
	  ,[PlanName]
	  ,[DateStr]
      ,[qty]
      ,[avg]
      ,[cnt]
	  ,[Sand]
	  ,[drySand]
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
	  ,[PlanName]
	  ,[DateStr]
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
) AS T3
group by LotProdID,RawMat
) AS T4 left outer join [PLAN]
on  T4.DateStr  = [PLAN].StartTime
and T4.PlanName = [PLAN].PlanName
order by RecTime DESC