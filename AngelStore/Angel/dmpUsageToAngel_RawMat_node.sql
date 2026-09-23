
MERGE [dmpUsageToAngel_RawMat] AS nTARGET
USING (SELECT * FROM [UsageToAngel_RawMat]) AS nSOURCE
ON 
[nSOURCE].[RawMat]    = [nTARGET].[RawMat]    AND 
[nSOURCE].[RecTime]   = [nTARGET].[RecTime]     
WHEN MATCHED --AND [nSOURCE].[TestValue] <> [nTARGET].[TestValue] 
THEN

UPDATE SET                                 
       [nTARGET].[dt]         = [nSOURCE].[dt]                            
      ,[nTARGET].[RecTime]    = [nSOURCE].[RecTime]                
      ,[nTARGET].[fdt]        = [nSOURCE].[fdt]                    
      ,[nTARGET].[mTime]      = [nSOURCE].[mTime]                  
      ,[nTARGET].[RawMat]     = [nSOURCE].[RawMat]                 
      ,[nTARGET].[qty]        = [nSOURCE].[qty]                    
      ,[nTARGET].[LotProdID]  = [nSOURCE].[LotProdID]     
	  ,[nTARGET].[PlanName]   = [nSOURCE].[PlanName]  
	  ,[nTARGET].[DateStr]    = [nSOURCE].[DateStr] 

--WHEN NOT MATCHED BY nSOURCE THEN DELETE
WHEN NOT MATCHED THEN
INSERT (
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[RawMat]
      ,[qty]
      ,[LotProdID]                   
	  ,[PlanName]    
	  ,[DateStr]
)
VALUES (
       [nSOURCE].[dt]                            
      ,[nSOURCE].[RecTime]                
      ,[nSOURCE].[fdt]                    
      ,[nSOURCE].[mTime]                  
      ,[nSOURCE].[RawMat]                 
      ,[nSOURCE].[qty]                    
      ,[nSOURCE].[LotProdID]       
	  ,[nSOURCE].[PlanName] 
	  ,[nSOURCE].[DateStr]
);
--wOUTPUT deleted.*, $action, inserted.* INTO #LoggingTable;
  

