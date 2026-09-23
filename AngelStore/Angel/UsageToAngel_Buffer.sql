SELECT 
       RefNumber		 
      --,ItemName	
	  ,row_number() over (partition by RefNumber order by ItemName) AS ItemNumber
	  ,MaterialNumber
      ,Quantity			 
	  ,Unit				
	  ,PlantCode
	  ,ValuationType
	  ,BatchNumber
	  ,Sloc
	  ,CostCenter
	  ,GLAccount
	  ,ApproveUserName
	  ,CreateSUserName
FROM(
SELECT 
       RefNumber		 
      ,T3.ItemName	
	  ,UsageMesToAngel_Materials.MaterialNumber
      ,Quantity			 
	  ,UsageMesToAngel_Materials.Unit				
	  ,PlantCode
	  ,ValuationType
	  ,BatchNumber
	  ,Sloc
	  ,CostCenter
	  ,GLAccount
	  ,ApproveUserName
	  ,CreateSUserName
	  ,T3.RecTime
      ,[PlanName]
      ,[DateStr]
      ,[MaterialCode]
      ,[NameThai]
      ,[Curve]
	  ,Product
FROM(
SELECT 
       RefNumber		 
      ,T2.ItemName		
	  ,MaterialNumber
      ,Quantity			 
	  ,Unit				
	  ,PlantCode
	  ,ValuationType
	  ,BatchNumber
	  ,Sloc
	  ,UsageMesToAngel_GlAcc.CostCenter
	  ,UsageMesToAngel_GlAcc.GLAccount
	  ,ApproveUserName
	  ,CreateSUserName
	  ,T2.RecTime
      ,[PlanName]
      ,[DateStr]
      ,[MaterialCode]
      ,[NameThai]
      ,T2.[Curve]
	  ,T2.Product
FROM(
SELECT 
       [LotProdID]		AS RefNumber		--เลขที่ใบเบิก Auto generate by MES
      ,[RawMat]			AS ItemName			--Item ในใบเบิกนั้นๆ Auto generate by MES
	  ,'30100361002'	AS MaterialNumber
      ,[qty]			AS Quantity			--รายละเอียดตามตาราง Materials Master 
	  ,'TON'			AS Unit				--รายละเอียดตามตาราง Materials Master 
	  ,'3031'			AS PlantCode		--PLANT
	  ,'NEW'			AS ValuationType    --Valuation Type เป็น NEW
	  ,'FreeText'		AS BatchNumber		--Free Text เพิ่มในหน้า QC Adjust
	  ,'FreeText'		AS Sloc				--Free Text เพิ่มในหน้า QC Adjust
	  ,'030C-230000'	AS CostCenter		--ตาราง PIS Material by Curve     , UsageMesToAngel_GlAcc
	  ,'523151'			AS GLAccount		--ตาราง PIS Material by Curve     , UsageMesToAngel_GlAcc
	  ,'sarojj'			AS ApproveUserName	--ตาราง Username 
	  ,'attagons'		AS CreateSUserName  --ตาราง Username
	  ,[RecTime]
      ,[PlanName]
      ,[DateStr]
      ,[MaterialCode]
      ,[NameThai]
      ,[Curve]
	  ,CASE WHEN Curve like 'Smooth Cool' THEN 'Smooth Cool_Tile_CB' ELSE 'CPAC_Tile_CB' END AS Product
FROM(
SELECT 
       [dt]
      ,[RecTime]
      ,[fdt]
      ,[mTime]
      ,[LotProdID]
      ,[RawMat]
      ,[qty]
      ,[avg]
      ,[cnt]
      ,[Sand]
      ,[pWGH1]
      ,[pWGH2]
      ,[pWGH3]
      ,[pWGH4]
      ,[PlanName]
      ,[DateStr]
      ,[MaterialCode]
      ,[NameThai]
      ,[Curve]
  FROM [UsageMesToAngel_RawMatByLot]
) AS T1
--where RawMat <> 'Sand'
) AS T2 left outer join UsageMesToAngel_GlAcc
on  T2.Product  = UsageMesToAngel_GlAcc.Product
and T2.ItemName = UsageMesToAngel_GlAcc.ItemName
) AS T3 left outer join UsageMesToAngel_Materials
on T3.ItemName = UsageMesToAngel_Materials.ItemName
) AS T4
order by RefNumber desc,ItemName,RecTime DESC
