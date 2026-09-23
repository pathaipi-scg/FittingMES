/****** Script for SelectTopNRows command from SSMS  ******/
SELECT 
       dt                                     
      ,RecTime                
      ,fdt                 
      ,mTime                
      ,LotProdID                
      ,Sand  
	  ,Sand*(1-avgSandMoist2/10000.0) AS drySand
      ,pWGH1                    
      ,pWGH2                        
      ,pWGH3                    
      ,pWGH4                
      ,qtySandMoist  
	  ,cntSandMoist
	  ,avgSandMoist 
	  ,avgSandMoist2
FROM(
SELECT 
       dt                                     
      ,RecTime                
      ,fdt                 
      ,mTime                
      ,LotProdID                
      ,Sand  
	  --,Sand*(1-avgSandMoist/10000.0) AS drySand
      ,pWGH1                    
      ,pWGH2                        
      ,pWGH3                    
      ,pWGH4                
      ,qtySandMoist  
	  ,cntSandMoist
	  ,avgSandMoist 
	  ,CASE WHEN avgSandMoist2 > 600 THEN avgSandMoist2/2 ELSE avgSandMoist2 END AS avgSandMoist2
FROM(
SELECT 
       dt                                     
      ,RecTime                
      ,fdt                 
      ,mTime                
      ,LotProdID                
      ,Sand  
	  --,Sand*(1-avgSandMoist/10000.0) AS drySand
      ,pWGH1                    
      ,pWGH2                        
      ,pWGH3                    
      ,pWGH4                
      ,qtySandMoist  
	  ,cntSandMoist
	  ,avgSandMoist 
	  ,CASE WHEN avgSandMoist2 > 6000 THEN avgSandMoist2 /10 ELSE avgSandMoist2 END AS avgSandMoist2
FROM(
SELECT 
       dt                                     
      ,RecTime                
      ,fdt                 
      ,mTime                
      ,LotProdID                
      ,Sand  
	  --,Sand*(1-avgSandMoist/10000.0) AS drySand
      ,pWGH1                    
      ,pWGH2                        
      ,pWGH3                    
      ,pWGH4                
      ,qtySandMoist  
	  ,cntSandMoist
	  ,avgSandMoist 
	  ,CASE WHEN cntSandMoist > 0 THEN  qtySandMoist/cntSandMoist ELSE 400 END AS avgSandMoist2
FROM(
SELECT 
       MAX([dt]        ) AS [dt]                                 
      ,MAX([RecTime]   ) AS [RecTime]                
      ,MAX([fdt]       ) AS [fdt]                
      ,MAX([mTime]     ) AS [mTime]              
      ,MAX([LotProdID] ) AS [LotProdID]   
	  ,MAX(Sand        ) AS Sand 
      ,MAX(pWGH1       ) AS pWGH1                    
      ,MAX(pWGH2       ) AS pWGH2                        
      ,MAX(pWGH3       ) AS pWGH3                    
      ,MAX(pWGH4       ) AS pWGH4      
	  ,MAX(qtySandMoist) AS qtySandMoist
	  ,MAX(cntSandMoist) AS cntSandMoist
	  ,MAX(avgSandMoist) AS avgSandMoist
FROM(
SELECT 
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[RawMat]
      ,[LotProdID]
      ,CASE WHEN RawMat='pWGH1' THEN [avg] ELSE null END AS pWGH1
	  ,CASE WHEN RawMat='pWGH2' THEN [avg] ELSE null END AS pWGH2
      ,CASE WHEN RawMat='pWGH3' THEN [avg] ELSE null END AS pWGH3
	  ,CASE WHEN RawMat='pWGH4' THEN [avg] ELSE null END AS pWGH4
	  ,CASE WHEN RawMat='Sand'  THEN [qty] ELSE null END AS Sand
	  ,CASE WHEN RawMat='SandMoist'  THEN [qty] ELSE null END AS qtySandMoist
	  ,CASE WHEN RawMat='SandMoist'  THEN [cnt] ELSE null END AS cntSandMoist
	  ,CASE WHEN RawMat='SandMoist'  THEN [avg] ELSE null END AS avgSandMoist
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
      ,[qty]
      ,[avg]
      ,[cnt]
  FROM [UsageToAngel_ByLot]
  where RawMat = 'pWGH1'
  or RawMat = 'pWGH2'
  or RawMat = 'pWGH3'
  or RawMat = 'pWGH4'
  or RawMat = 'Sand'
  or RawMat = 'SandMoist'
) AS T1
) AS T2
GROUP BY LotProdID 
) AS T3
) AS T4
) AS T5
) AS T6
order by RecTime DESC