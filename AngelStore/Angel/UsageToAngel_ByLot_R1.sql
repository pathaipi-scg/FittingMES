/****** Script for SelectTopNRows command from SSMS  ******/
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
FROM(
SELECT
	   [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[RawMat]
      ,[LotProdID]
      ,CAST([qty] AS DECIMAL(10,1)) AS [qty]                          
      ,CAST([avg] AS DECIMAL(10,1)) AS [avg]            
      ,CAST([cnt] AS DECIMAL(10,0)) AS [cnt]    
FROM(
SELECT
	   MAX([dt]       ) AS [dt]                            
      ,MAX([RecTime]  ) AS [RecTime]                        
      ,MAX([fdt]      ) AS [fdt]                        
      ,MAX([mTime]    ) AS [mTime]                      
      ,MAX([RawMat]   ) AS [RawMat]       
	  ,MAX([LotProdID]) AS [LotProdID]  
      ,SUM([qty]      ) AS [qty]                      
	  ,COUNT([qty])		AS [cnt]
	  ,AVG([qty])		AS [avg]
FROM(
SELECT
	   [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[RawMat]
      ,CAST([qty] AS REAL) AS qty
      ,[LotProdID]
FROM [dmpUsageToAngel_RawMat]
) AS T1
GROUP BY LotProdID,RawMat
) AS T2
) AS T3
order by RecTime DESC
