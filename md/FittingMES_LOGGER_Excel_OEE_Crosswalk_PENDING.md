# LOGGER-to-Excel OEE Crosswalk — Live Mapping Snapshot

## Status

The PRINT OEE report reads category codes from the live LOGGER masters using
the effective-code rule
`COALESCE(NULLIF(sub.OEEExcelCode,N''),NULLIF(main.OEEExcelCode,N''))`.
This document records a read-only snapshot of those values; it does not
authorize or make a Master Maintenance change.

The information below was collected by read-only inspection of the active
LOGGER masters and existing F-machine mappings. No SB23 data or master records
were changed.

## Verified live OEEExcelCode values

| Type | StopId | StopType | Main OEEExcelCode |
|---|---:|---|---|
| Main | 2 | SETUP | ก.1 |
| Main | 5 | CLEAN | NULL |
| Main | 6 | SMDT | NULL |
| Main | 7 | BD | ค.1 |

| StopId | StopType | SubStopId | SubStopType | Sub OEEExcelCode |
|---:|---|---:|---|---|
| 3 | CHGOVER | 3 | เปลี่ยน Color | ก.2 |
| 3 | CHGOVER | 5 | เปลี่ยน Mould | ก.3 |
| 3 | CHGOVER | 6 | เปลี่ยนผ้าตะแกรง | ก.4 |
| 4 | IDLE | 7–13 | Existing IDLE subtypes | ง.1–ง.7, in SubStopId order |
| 5 | CLEAN | 14 | Clean ระหว่างผลิต | ก.5 |
| 5 | CLEAN | 15 | Clean หลังผลิต | ก.5 |
| 6 | SMDT | 16–20 | Existing SMDT subtypes | ค.2–ค.6, in SubStopId order |
| 7 | BD | 21 | -- | NULL; falls back to Main ค.1 |

The main fallback codes for CLEAN (`ก.5`) and SMDT (`ข.1`) are not saved in
the live master records. Therefore, StopId 5 without a classified subtype has
no effective code, and StopId 6 without a classified subtype has no effective
code. The report must show affected categories as unavailable when such an
event is present; it must not infer the missing Main mappings from the
classified subtype codes.

## Excel category definitions

| Section | Excel category |
|---|---|
| ก | ก.1 เตรียมการผลิต |
| ก | ก.2 หยุดเปลี่ยนสี |
| ก | ก.3 หยุดเปลี่ยนโมล |
| ก | ก.4 หยุดเปลี่ยนผ้าตะแกรง |
| ก | ก.5 ทำความสะอาดหลังผลิต |
| ข | ข.1 ปรับตั้งเครื่องจักร |
| ข | ข.2 เครื่องจักรหยุด < 10 นาที |
| ค | ค.1 เครื่องจักรเสียตั้งแต่ 10 นาที ขึ้นไป |
| ค | ค.2 ผู้รับเหมาทำไม่ทัน |
| ค | ค.3 รถ Fork lift เสีย / วิ่งไม่ทัน |
| ค | ค.4 วัตถุดิบหมด |
| ค | ค.5 รอแบบ |
| ค | ค.6 อื่น ๆ |
| ง | ง.1 ไม่มีแผนผลิต |
| ง | ง.2 ทดลองผลิต |
| ง | ง.3 ที่กองเต็ม |
| ง | ง.4 ไม่มีแบบ |
| ง | ง.5 ไฟฟ้าดับ / น้ำประปาไม่ไหล |
| ง | ง.6 ครอบไม่แห้งรอแกะ |
| ง | ง.7 อื่น ๆ |

## Active LOGGER Type IDs

| StopId | StopType |
|---:|---|
| 1 | RUN |
| 2 | SETUP |
| 3 | CHGOVER |
| 4 | IDLE |
| 5 | CLEAN |
| 6 | SMDT |
| 7 | BD |

## Active LOGGER Sub Type IDs

| SubStopId | StopId | SubStopType |
|---:|---:|---|
| 1 | 1 | -- |
| 2 | 2 | -- |
| 3 | 3 | เปลี่ยน Color |
| 5 | 3 | เปลี่ยน Mould |
| 6 | 3 | เปลี่ยนผ้าตะแกรง |
| 7 | 4 | ไม่มีแผนผลิต |
| 8 | 4 | ทดลองผลิต |
| 9 | 4 | ที่กองเต็ม |
| 10 | 4 | ไม่มีแบบ |
| 11 | 4 | ไฟฟ้าดับ/น้ำประปาไม่ไหล |
| 12 | 4 | ครอบไม่แห้งรอแกะ |
| 13 | 4 | อื่นๆ |
| 14 | 5 | Clean ระหว่างผลิต |
| 15 | 5 | Clean หลังผลิต |
| 16 | 6 | ผู้รับเหมาทำไม่ทัน |
| 17 | 6 | Forklift เสีย / วิ่งไม่ทัน |
| 18 | 6 | วัตถุดิบหมด |
| 19 | 6 | รอแบบ |
| 20 | 6 | อื่นๆ |
| 21 | 7 | -- |

## Active Cause mappings for main machine F (McId 7)

| CauseId | Cause | McId | SubMcId | StopId | SubStopId | MEO |
|---:|---|---:|---:|---:|---:|---|
| 1 | ปูนติดโมล | 7 | 3 | 6 | 20 | O |
| 2 | ชิ้นแห่คอถ้วยจ่าย | 7 | 5 | 6 | 20 | O |
| 4 | Robot Alarm เคลียร์งาน | 7 | 12 | 6 | 20 | O |
| 5 | ทำความสะอาด ชุดจ่ายปูน/โม่/Mix | 7 | 6 | 5 | 14 | M |
| 6 | เคลียร์ปูนที่เรือ | 7 | 2 | 6 | 20 | O |
| 8 | ปรับตั้งเครื่องจักร น้อยกว่า 10 นาที | 7 | 13 | 6 | 20 | M |
| 13 | ปรับตั้งชุดรับแบบ | 7 | 7 | 6 | 20 | M |
| 14 | ปรับตั้งชุดเสริฟ | 7 | 8 | 6 | 20 | M |
| 15 | ปรับตั้งชุดวาง Product กลาง Line | 7 | 14 | 6 | 20 | M |
| 16 | ปรับตั้งโมล | 7 | 3 | 2 | 2 | M |
| 17 | แบบขัดตัว | 7 | 12 | 6 | 20 | M |
| 18 | อื่นๆ | 7 | 26 | 6 | 20 | M |

## Unresolved mappings and relationships

1. `Fitting_Cause` records identify LOGGER Type, Sub Type, Cause, machine and
   sub-machine relationships, but do not identify an Excel OEE category.
2. The active F mappings include SMDT Cause rows and some SETUP/CLEAN rows;
   there is no approved rule assigning these rows to Excel sections ก, ข, ค
   or ง.
3. Category assignment follows only the saved effective OEEExcelCode; Cause
   and M/E/O labels do not override it. Category totals use the persisted
   `LoggerEvent.DurationMin` once per unique `LoggerEventID`. Distinct
   overlapping events are summed as separately recorded durations; no
   interval-clipping or overlap adjustment is applied.
4. At least one observed F7 LOGGER event uses `CauseId 11` with the stored
   Cause label `รอปูน` and a Related Main Machine identity. That cause is not
   in the direct F (`McId 7`) Cause list above. The approved cross-machine
   Cause/proxy relationship and its Excel category are unresolved.
5. Excel category ก.1 and ค.1 are available through Main fallback; ก.2–ก.5,
   ค.2–ค.6 and ง.1–ง.7 are available through their saved SubStop codes.
   Categories ข.1 and ข.2 have no saved effective master code in the inspected
   masters and remain unavailable rather than being shown as zero.
6. LOGGER events without a valid SubStop-to-StopType relationship, without a
   supported effective code, with invalid duration, duplicate event identity,
   or without a unique Press/Shift association cannot be safely included.
   Such records remain visible with original identifiers and labels in the
   report's LOGGER detail section.
7. Classified and unclassified LOGGER durations are for category reporting
   only. They do not feed the existing OEE MANUAL downtime calculation.

The saved OEEExcelCode values are the only classification authority. Missing
codes remain unavailable, not zero, and LOGGER durations must not be used as
OEE losses.
