/****** Script for SelectTopNRows command from SSMS  ******/
SELECT 
       dt,RecTime,fdt
	  ,DATEADD(MINUTE,ROUND(DATEDIFF(MINUTE, 0, dateadd(second,-1,RecTime)) / 1.0, 0) * 1, 0) AS mTime
      ,REPLACE(RawM3,'_','') AS RawMat
      ,qty
	  ,LotProdID
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM2,'MODBUS.MIX.USAGE.','') AS RawM3
      ,qty
FROM (
SELECT 
       RecTime
      ,REVERSE(Raw2) AS RawM2
      ,qty
FROM (
SELECT 
       RecTime
      ,substring(RawM1,1,charindex('_',RawM1)) AS Raw2
      ,qty
FROM (
SELECT 
       RecTime
      ,REVERSE(RawM10) AS RawM1
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM09,'_PV','PV') AS RawM10
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM08,'_Log','Log') AS RawM09
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM07,'_FML','FML') AS RawM08
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM06,'CB_MODBUS.CLR2.','_clr2') AS RawM07
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM05,'CB_MODBUS.CLR1.','_clr1') AS RawM06
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM04,'SAND_AVG','_avgSmoist') AS RawM05
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM03,'MORTAR_AVG','_avgMmoist') AS RawM04
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM02,'SPEED_','speed') AS RawM03
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(RawM01,'AVG_','avg') AS RawM02
      ,qty
FROM (
SELECT 
       RecTime
      ,REPLACE(Raw0,'PERCENT_','p') AS RawM01
      ,qty
FROM (
SELECT 
       [_TIMESTAMP] AS RecTime
      ,[_NAME]		AS Raw0
      ,[_VALUE]		As qty
  FROM [MixSand]
  WHERE _TIMESTAMP >= dateadd(day,-10,getdate())
UNION
SELECT 
       [_TIMESTAMP] AS RecTime
      ,[_NAME]		AS RawMat
      ,[_VALUE]		As qty
  FROM [MixUsage]
  WHERE _TIMESTAMP >= dateadd(day,-10,getdate())
UNION
SELECT 
       [_TIMESTAMP] AS RecTime
      ,[_NAME]		AS RawMat
      ,[_VALUE]		As qty
  FROM [CLR1]
  WHERE _TIMESTAMP >= dateadd(day,-10,getdate())
UNION
SELECT 
       [_TIMESTAMP] AS RecTime
      ,[_NAME]		AS RawMat
      ,[_VALUE]		As qty
  FROM [CLR2]
  WHERE _TIMESTAMP >= dateadd(day,-10,getdate())
) AS T1
) AS T2
) AS T3
) AS T4
) AS T5
) AS T6
) AS T7
) AS T8
) AS T9
) AS T10
) AS T11
) AS T12
) AS T13
) AS T14
) AS T15,nLOTP_FAST
where T15.RecTime between dt and fdt

