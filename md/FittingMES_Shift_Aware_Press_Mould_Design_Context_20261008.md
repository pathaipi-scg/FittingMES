# FittingMES — Shift-aware Press / Mould / Fitting

> **เอกสารบริบทและข้อกำหนดสำหรับใช้ต่อกับ GitHub Copilot**<br>
> วันที่จัดทำ: 2026-10-08<br>
> โครงการ: `D:\AI\FittingMES` · Database: `SB23`<br>
> Git checkpoint ล่าสุดที่ยืนยัน: `e01a0ece6c915e011a9cf9f95406da95b2e73bb0` (`main` = `origin/main`, worktree clean ณ เวลาตรวจสอบ)
> **สถานะ: วิเคราะห์และกำหนดกติกาเท่านั้น — ยังไม่ได้สั่ง Copilot แก้ Shift-aware, ยังไม่รัน Migration**

## 1. เป้าหมาย

ปรับหน้า Production ส่วน **ADD FITTING / PRESS PRODUCTION** ให้การติดตั้ง Press + Mould และข้อมูลการผลิต **แยกตาม Production Lot + Shift** โดยตรง แทนการมี Press หนึ่งแถวที่เก็บเวลาของ Shift 1 และ Shift 2 ปะปนกัน ต้องรองรับการย้าย Mould เมื่อเครื่องเสียภายในกะด้วย `RELEASE MOULD` โดยเก็บประวัติเดิมไว้ และรองรับการแก้ไขรายการด้วย `EDIT FITTING` ที่แยกจาก RELEASE อย่างชัดเจน

**ห้ามเริ่มเขียนโค้ดหรือเปลี่ยน DB จากเอกสารนี้ทันที** ต้องอนุมัติ design, preflight, migration และข้อกำหนดที่ยังไม่ตกลงก่อน

## 2. ข้อกำหนดธุรกิจที่ยืนยันแล้ว

### 2.1 การเพิ่ม Fitting แยกกะ

- ฟอร์ม `ADD FITTING` ต้องมี **Shift | Press | Mould | ADD FITTING**
- พนักงานต้องเลือก Shift 1 หรือ Shift 2 **อย่างชัดเจน** ก่อน ADD
- แม้ Shift 2 จะใช้ Press และ Mould เดิมจาก Shift 1 ก็ต้อง **ADD FITTING ใหม่** เป็นคนละ assignment/record
- PRESS PRODUCTION ต้องมีคอลัมน์ **Shift** ให้เห็นว่าข้อมูลของแถวนั้นเป็นกะใด
- Counter, Curing, Dispatch และเวลาที่กรอกใน Press Production ต้องเป็นข้อมูลของ assignment/กะนั้น ไม่เอาสองกะมารวมอยู่ในแถวเดียว (การ reconcile กับยอดระดับ Lot ยังต้องออกแบบ)

### 2.2 กติกา Mould Availability — **ยืนยันล่าสุด**

**Mould หนึ่งตัวมี active assignment ได้เพียงหนึ่งรายการในชุด `Production Date + Shift` เดียวกัน โดยไม่สนว่าเป็น Lot ไหนหรือ Press ไหน**

- Mould ถูก ADD เข้า Press ใน Lot A / Shift 1 แล้ว → Lot B / Shift 1 หรือ Press อื่นใน Shift 1 **เลือก Mould เดียวกันไม่ได้** ตราบที่ assignment เดิมยัง active
- พอเปลี่ยนเป็น Shift 2 → Mould นั้น **พร้อมให้เลือกใหม่อัตโนมัติ** ไม่ต้อง RELEASE จาก Shift 1
- Shift 2 จะใช้ Mould เดิมกับ Press/Lot เดิมก็ได้ แต่ **ต้อง ADD FITTING ใหม่** สำหรับ Shift 2
- หาก Mould ถูก ADD แล้วใน **Shift 2** ของ Lot B → Lot C / Shift 2 **เลือกไม่ได้** จนกว่า assignment ใน Shift 2 ที่ครอบครอง Mould จะ RELEASE
- คนละ **Production Date** ไม่ชนกันตามกติกา assignment ปัจจุบัน (ต้องระวัง run จริงข้ามช่วงเวลา/กะ และใช้ production-day rules ไม่ใช่ `CAST(GETDATE() AS date)` อย่างเดียว)
- การตรวจสอบต้องทำ **ฝั่ง server และปลอดภัยต่อ concurrent requests** ไม่ใช่กรอง dropdown อย่างเดียว

ตัวอย่าง (Production Date เดียวกัน):

| ลำดับ | Lot | Shift | Press | Mould | ผล |
|---|---|---|---|---|---|
| 1 | A | 1 | F7 | A | ADD ได้ |
| 2 | B | 1 | F8 | A | ADD ไม่ได้ เพราะรายการ 1 ยัง active |
| 3 | B | 2 | F8 | A | ADD ได้ เพราะคนละ Shift |
| 4 | C | 2 | F9 | A | ADD ไม่ได้ เพราะรายการ 3 ยัง active |
| 5 | B | 2 | F8 | A | RELEASE รายการ 3 เพื่อให้ Mould ว่างใน Shift 2 |
| 6 | C | 2 | F9 | A | ADD ได้หลัง RELEASE รายการ 3 |

> กติกานี้อ้างอิง **Production Date ของ Lot + Shift ของ assignment** ไม่ใช่ “Mould ถูกใช้ใน Lot เดียวกันเท่านั้น” และไม่ใช่ “Mould ใช้ได้เพียงครั้งเดียวตลอดวัน”

### 2.3 RELEASE MOULD — **ยังต้องมี**

- **อย่าลบ RELEASE MOULD ออกจากระบบ** (แก้ไขจากความเข้าใจเดิมที่เคยคิดว่าจะถอดปุ่มออก)
- ใช้เมื่อจำเป็นต้องถอด/ย้าย Mould **ภายใน Shift เดียวกัน** เช่น F7 เครื่องเสีย ต้องถอด Mould A ไปให้ F8 ผลิตต่อ
- RELEASE ทำให้ assignment เดิม **ไม่บล็อกการเลือก Mould** ใน Production Date + Shift นั้นอีกต่อไป
- RELEASE **ต้องรักษาประวัติ** PressProduction, Counter/Curing/Dispatch, MouldUsage, downtime และ LOGGER เดิม ไม่ลบหรือรีเซ็ตยอด
- เมื่อเปลี่ยน Shift ตามปกติ **ไม่ต้อง RELEASE** เพื่อให้กะถัดไปใช้ Mould
- ต้องออกแบบตำแหน่ง/วิธีกด RELEASE ใน UI ให้ชัดและไม่กดผิด โดยแยกจาก EDIT FITTING
- พฤติกรรม undo-release ปัจจุบันต้องตรวจสอบผลกระทบต่อการจัดสรรใหม่; ห้ามแก้แบบทำให้มี active ซ้อน

### 2.4 EDIT FITTING — แยกจาก RELEASE

- เลือกแถว Press Production เดิมเพื่อแก้ไข (แนวทางคล้าย LOGGER: select row → ฟอร์มเติมค่าเดิม)
- โหลด Shift, Press, Mould เดิมขึ้นฟอร์ม และเปลี่ยนปุ่มเป็น `EDIT FITTING`
- EDIT ต้อง **แก้ไข record เดิม** ไม่สร้าง record ซ้ำ และควรมี Cancel กลับโหมด ADD
- ต้องตรวจ conflict Mould/Press/Shift ใหม่อีกครั้งแบบ transactional
- EDIT ต้องรองรับการแก้ Shift, Press และ Mould **แม้กรอก Counter/Curing แล้ว** โดย UPDATE `PressProductionID` เดิม ไม่ INSERT assignment ใหม่
- เมื่อเปลี่ยน Mould ให้ตรวจ availability จาก `Production Date + Shift + MouldID` ครอบคลุมทุก Lot/Press; ยกเว้น assignment ที่กำลังแก้จากการตรวจ conflict ของตัวเอง และปฏิเสธถ้ามี active assignment อื่นครอบครอง Mould ในวัน/กะเดียวกัน
- การแก้ต้อง reconcile Counter/Curing, MouldUsage และ dependent records อย่างถูกต้อง ไม่ double-count usage และไม่ย้าย/แก้ข้อมูลประกอบโดยเงียบ ๆ
- ข้อมูล Counter/Curing, downtime หรือ LOGGER ที่มีอยู่ **ไม่ห้าม EDIT โดยตัวมันเอง**; implementation ต้องกำหนดและทดสอบการ reconcile/คงความสัมพันธ์ของแต่ละ dependent record ก่อนเปิดใช้งาน
- `EquipmentTimeEvent` ระบุ `ProductionID + EquipmentCode + ShiftID` แต่ไม่มี `PressProductionID`; เมื่อแก้ Press/Shift ให้ตรวจเฉพาะ identity เดิมและเป้าหมายของ Lot/กะนั้น ถ้ามี event ให้ปฏิเสธพร้อมระบุ identity ที่ชน ห้ามย้ายหรือเขียนทับ event
- `LoggerEvent` ระบุ `ProductionDate + McId + McInstanceNo + ShiftID` แต่ไม่มี `ProductionID` หรือ `PressProductionID`; การมี LOGGER ของเครื่องอื่นหรือคนละ Shift ในวันเดียวกันต้องไม่ขวาง EDIT ตรวจเฉพาะ Press/Shift เดิมและเป้าหมาย และปฏิเสธพร้อมระบุ conflict หากพบ event ที่ตรง identity; event ที่ `ShiftID` เป็น NULL สำหรับ Press เดียวกันให้รายงานว่าไม่สามารถระบุ Shift ได้อย่างปลอดภัย ห้ามเดา/ย้าย/เขียนทับ LOGGER
- การแก้ Mould อย่างเดียวไม่เปลี่ยน identity ของ Press/Shift จึงไม่ติดข้อจำกัดการ reconcile LOGGER หรือ `EquipmentTimeEvent`; `MouldUsage` เดิมต้อง update in place โดยรักษา `PressProductionID`, ใช้ `ReconditionNo` ของ Mould เป้าหมายเมื่อเปลี่ยน Mould และตั้ง `UsageCycles` ตาม Counter ล่าสุด
- `EquipmentTimeEvent` ยังไม่มี identity ระดับ `PressProductionID`; หาก Lot/Press/Shift เดียวกันมีหลาย assignment episodes จะไม่สามารถแบ่ง downtime ย้อนหลังอย่างปลอดภัยได้ จนกว่าจะมีความสัมพันธ์ระดับ episode ระบบจึงต้องป้องกันการบันทึก downtime ใหม่ให้ identity นี้ และต้องแสดง/ทำเครื่องหมาย OEE ว่าไม่สามารถคำนวณ episode นั้นได้ แทนการนับ downtime ซ้ำหรือเดา assignment

### 2.5 แนวทางข้อมูลเดิมและ migration — ยืนยันล่าสุด

- ข้อมูล Production ปัจจุบันเป็น **DEMO data**; ไม่จำเป็นต้องใช้ความพยายามมากเกินไปเพื่อสร้าง Shift ย้อนหลังให้ครบ
- **การตัดสินใจล่าสุด:** ห้าม migration กำหนด Shift ให้ PressProduction แถวเดิม; คง `ShiftMasterID = NULL` เพราะไม่มีหลักฐานยืนยัน historical Shift แม้ข้อมูลจะเป็น DEMO
- Resolve `ShiftMaster.id` จาก `ShiftCode` สำหรับ ADD/EDIT ใหม่เท่านั้น; ห้าม hardcode ID หรืออนุมาน Shift เดิมจาก Lot, เวลา, LOGGER หรือ `EquipmentTimeEvent`
- `EquipmentTimeEvent.ShiftID` เป็น identity แยกจาก `PressProduction.ShiftMasterID`; ตรวจ MANUAL Shift 2 events ที่ผูกด้วย `ProductionID + EquipmentCode` ก่อน migration ห้ามลบ รวม หรือ re-key โดยอัตโนมัติ
- Migration 027 ไม่อ่านหรือแก้ `EquipmentTimeEvent`; preflight รายงาน MANUAL Shift 2 events และ natural-key collisions เพื่อบันทึกสภาพข้อมูลเท่านั้น ไม่ใช้เป็น backfill หรือ migration gate
- MANUAL Shift 2 events ทุกแถวยังคง natural key และ duration เดิม แม้มี Shift 1 natural-key counterpart; ห้ามเปลี่ยน `ShiftID` เพราะอาจชน unique key `ProductionID + EquipmentCode + ShiftID + TimeType + SourceType`
- แถวใหม่ที่สร้างหลังเปิดใช้ workflow ต้องมี Shift ที่ resolve จาก `ShiftMaster.ShiftCode` แล้วเก็บ `ShiftMaster.id`; ID เป็น opaque ห้ามตีความว่า ID เท่ากับ Shift number
- ก่อน migration ให้รายงาน active Mould ซ้ำที่ Production Date เดียวกันเป็น **รายการที่ต้องตรวจสอบ** เท่านั้น เพราะ assignment เก่ายังไม่มี Shift จึงยังตัดสินไม่ได้ว่าเป็น conflict จริงหรือไม่
- Rollback ต้องไม่ลบหรือรวม assignment/ยอดหรือแก้ EquipmentTimeEvent: เมื่อมี `ShiftMasterID` ถูกกำหนดให้ assignment หลัง migration แล้ว ให้ปฏิเสธ schema-only rollback และใช้ pre-migration backup เพื่อกู้คืนแทน เพราะการ drop column จะทำให้ Shift assignment สูญหาย

## 3. กติกาเวลาและ Shift

- ตรวจสอบ SB23 จริงแล้ว `ProductionShiftRuleHistory` มีผลตั้งแต่ `2026-01-01`: **Shift 1 เริ่ม 06:00**, **Shift 2 เริ่ม 19:00**
- ไฟล์ migration `018_production_shift_rule_history.sql` เคย seed Shift 2 เป็น `20:00` แต่ **live SB23 เป็น 19:00**: ห้ามรัน seed ซ้ำหรือเปลี่ยนค่าจริงกลับโดยไม่อนุมัติ
- Shift boundary ต้อง resolve จาก **effective-dated `ProductionShiftRuleHistory`** ของวันผลิตที่เกี่ยวข้อง ไม่ hardcode เวลาในโค้ด
- `Production Date` ต้องใช้ความหมายวันผลิตตาม `ProductionDayRuleHistory` / cutoff ของระบบ และ `ProductionLot.ProdDate` ตามที่ระบบบันทึก ไม่ใช้วันที่ปฏิทินแทนโดยไม่ตรวจสอบ
- ประวัติที่เคยมี cutoff วันผลิต 08:00 ไม่ได้แปลว่า Shift 1 ต้องเริ่ม 08:00: **production-day cutoff และ shift start เป็นกฎคนละชุด**
- ต้องทดสอบช่วงข้ามเที่ยงคืนและการเลือกวันผลิตย้อนหลัง

## 4. ข้อเท็จจริงจาก Step 1–2 (ตรวจโค้ดและ live SB23)

### 4.1 Skills/เอกสารที่ Copilot อ่านแล้วใน Step 2

- `skill/DATABASE_ID_FIRST_DESIGN_SKILL.md`
- `skill/FittingMES_LOGGER_Bidirectional_SKILL.md`
- `skill/FittingMES_LOGGER_Design_Context.md`
- `md/DATABASE.md` และ `md/DATABASE_updated.md`
- `docs/production-workflow.md`

**ข้อบังคับถาวร:** ทุกครั้งก่อนงาน DB/SQL/schema/migration/data ต้องค้นหาและ **อ่าน Database Skill ที่เกี่ยวข้อง** ก่อน, ยึด ID-first, reuse masters, ตรวจ live schema, รักษา legacy และรายงานสิ่งที่อ่าน ห้ามเดา skill path หรือใช้เพียงความจำ

### 4.2 Live SB23 schema ที่ยืนยัน

| Object | สิ่งที่ตรวจพบ |
|---|---|
| `ProductionLot` | PK `ProductionID`; `ProdDate` และ Lot-level `Shift` (nullable) |
| `PressProduction` | PK `PressProductionID`; `ProductionID`, `MachineCode`, `MouldID`, Dispatch/Counter/Curing, Start/End, Release fields; **ไม่มี assignment Shift** |
| `UX_PressProduction_Production_Machine` | **Unique `(ProductionID, MachineCode)`** — ขัดกับการ ADD F7 ซ้ำใน Lot เดิมคนละ Shift |
| `MouldMaster` | PK `MouldID`; reuse master เดิม |
| `MouldUsage` | PK `MouldUsageID`; unique `PressProductionID`; usage อ้างอิง assignment เดิม |
| `EquipmentTimeEvent` | มี `ShiftID`; MANUAL unique `(ProductionID, EquipmentCode, ShiftID, TimeType, SourceType)` ตาม filtered index |
| `ProductionShiftRuleHistory` | effective date + `ShiftID` + `StartTime`; ไม่มี FK ไป ShiftMaster |
| `ShiftMaster` | PK `id` bigint, unique `ShiftCode`; active ShiftCode `1`, `2` |
| `LoggerEvent` | `ShiftID` nullable; ไม่มี FK ตรงไป PressProduction assignment |

**สำคัญ:** แม้ ShiftMaster `id` ที่พบปัจจุบันตรงกับ ShiftCode 1/2 ห้ามสมมติว่า ID = Shift number เสมอ ต้อง resolve จาก `ShiftCode` แล้วใช้ PK จริง

### 4.3 ปริมาณข้อมูล live ณ Step 2 (เป็น snapshot ไม่ใช่ตัวเลขปัจจุบันถาวร)

- ProductionLot **18** rows; PressProduction **14**; MouldMaster **118**; MouldUsage **9**
- PressProduction 14 rows: ไม่มี Start **8**, ไม่มี End **10**, ไม่มี Counter **5**, Released **1**
- EquipmentTimeEvent **56**: MANUAL Shift 1 = **38**, Shift 2 = **18**
- LoggerEvent **10**: ShiftID 1 = **3**, ShiftID NULL = **7**
- ไม่พบ migration ledger แบบ authoritative จากการค้นชื่อตาราง; ตรวจสอบได้เพียงผลลัพธ์ของ migration ที่ deploy อยู่
- การตรวจสอบใช้ `app.database.get_connection()` กับ SB23 ด้วย SELECT-only; ยังไม่ได้พิสูจน์ว่า SQL login ถูกจำกัดสิทธิ์เป็น read-only

### 4.4 Code paths / จุดเสี่ยง

- ADD FITTING route: `POST /lots/{production_id}/press-production` ใน `app/main.py`; logic ใน `app/press_production.py`
- RELEASE route: `POST /lots/{production_id}/press-production/{press_production_id}/release`; ปัจจุบันเปลี่ยน `ReleasedAt`, `ReleasedBy`, `UpdatedAt` โดยไม่ลบข้อมูลเดิม
- ปัจจุบัน PressProduction หนึ่งแถวมี Shift 1 และ Shift 2 time inputs อยู่ในแถวเดียว และ time events ถูกเก็บแยก Shift
- `app/print_oee.py` และ Press Production details join EquipmentTimeEvent ตาม Lot+Machine **โดยไม่กรอง Shift ของ assignment** → หากเพิ่มสอง assignment ของ Press เดียวกัน อาจ duplicate loss minutes/OEE
- LOGGER เป็น machine/date/Shift summary ไม่ได้ FK ตรงกับ `PressProductionID`; อย่าผูก LOGGER เข้ากับ assignment โดยเดา
- `app/print_prod.py` ใช้ Lot-level ProductionData ไม่ใช่ per-Press assignment โดยตรง

## 5. แนวทางออกแบบที่ Copilot เสนอ (ยังไม่อนุมัติ migration)

ข้อเสนอในหมวดนี้เป็นสถานะก่อนการตัดสินใจใน Section 2.5 และ Step 7;
กติกาการ backfill legacy DEMO ในข้อเสนอเดิมถูก supersede แล้ว

1. **ใช้ `PressProduction` เดิม** เป็น assignment ไม่สร้างตารางใหม่ซ้ำโดยไม่จำเป็น
2. เพิ่ม `PressProduction.ShiftMasterID bigint NULL` และ FK → `ShiftMaster.id`; legacy rows คงเป็น NULL/unknown และ normal ADD/EDIT ต้องระบุ Shift
3. Migration จะเพิ่ม `PressProduction.ShiftMasterID bigint NULL` และ FK ไป `ShiftMaster.id`; สร้าง unique filtered index สำหรับ active assignment ที่มี Shift บน `(ProductionID, MachineCode, ShiftMasterID)` เมื่อ `ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL` เพื่อให้ RELEASE แล้ว ADD Press เดิมในกะเดิมได้ โดยคง released episodes เป็นประวัติ
4. Mould availability ตรวจ active assignment ตาม **Production Date + Shift + MouldID**, ครอบคลุมทุก Lot/Press, และ `ReleasedAt IS NULL`
5. MouldUsage ผูก `PressProductionID` ต่อไป แต่ต้องยืนยัน behavior เมื่อ RELEASE แล้ว reuse Mould ใน Shift เดิม รวมถึงยอด cycles และประวัติ
6. ตรวจ concurrency: ต้องมีวิธีป้องกัน double-allocation แบบ atomic ใน DB transaction (เช่น lock/serialization ที่เหมาะกับ key วันผลิต+กะ+Mould) และมี tests สำหรับ concurrent ADD/EDIT/RELEASE
7. ไม่เปลี่ยน `ProductionLot.Shift`, `EquipmentTimeEvent.ShiftID`, `LoggerEvent.ShiftID` หรือ master structure อื่นพร้อมกันโดยไม่จำเป็น; map ShiftCode ↔ ShiftMaster PK อย่างชัดเจน
8. Migration ต้องมี preflight, compatibility, rollback และ reconciliation ก่อน–หลัง; ห้ามแบ่งยอด historical Counter/Curing/Dispatch หรือ MouldUsage ข้าม Shift โดยเดา

## 6. ประเด็นสำคัญที่ต้องออกแบบ/ถามก่อนลงมือ

1. **Press เดิมใน Lot+Shift เดิมหลัง RELEASE:** อนุญาต ADD ใหม่อีกครั้งหรือไม่? เช่น Shift 1: F7/Mould A → RELEASE → Shift 1: F7/Mould B. หากอนุญาต ต้องออกแบบ uniqueness เป็น *active assignment* หรือมี sequence/period แทน unique `(ProductionID, MachineCode, ShiftMasterID)` ตรง ๆ
2. **Mould เดียวกันถูก RELEASE แล้วนำกลับมาใช้ใน Shift เดิม:** สามารถเกิดหลาย historical assignment ของ Mould เดียวกันได้ แต่ active พร้อมกันไม่ได้; ต้องออกแบบ query ให้ไม่ถือว่าประวัติ = การครอบครองปัจจุบัน
3. **EDIT หลังเริ่มผลิต:** อนุญาตแก้ Shift/Press/Mould แม้มี Counter/Curing; ต้องออกแบบ reconciliation ของ MouldUsage และ dependent records และทดสอบไม่ให้ยอดซ้ำ/ผิด assignment
4. **ข้อมูลเดิม — ตัดสินใจล่าสุด:** คง PressProduction เดิมเป็น Shift NULL/unknown; ห้ามเดาจากสถานะ DEMO, Lot-level Shift, start time, time event หรือ LOGGER
5. **OEE:** per-assignment per-shift Counter/Curing/Speed/loss ต้องไม่ซ้ำจาก joins; ต้องทดสอบ report หลังแยกกะ
6. **การ reconcile:** กำหนดความสัมพันธ์ยอด per-Press/Shift กับ Lot-level `ProductionData` และพฤติกรรมเมื่อมีหลาย assignment ใน Shift เดียว
7. **Shift boundary/cross-midnight:** ต้องแยก `Production Date` จาก calendar date และระบุช่วงเวลาของ Shift ตาม effective rule
8. **Release/Undo Release:** ต้องป้องกัน undo หาก Mould ถูกจัดสรร active ให้เครื่องอื่นแล้วใน Production Date+Shift เดียวกัน
9. **UI RELEASE:** ยังไม่กำหนดตำแหน่งปุ่มที่ปลอดภัย ต้องคง functionality แยกจาก select/edit; เพิ่ม confirmation/permission หากเหมาะสม
10. **OEE formulas (งานแยก ไม่ควรปน migration):** ผู้ใช้เคยระบุ `IdealRunTime = Counter / StandardSpeed`, `PR = IdealRunTime / AvailableTime`, `AR = AvailableTime / TotalWorkTime`, `OEE = AR × PR × QR`; QR ควร confirm ว่า `Curing/Counter` และนิยาม residual SMDT ยังต้องเคลียร์ก่อน implement

## 7. ลำดับทำงานต่อจากนี้ (ทีละ Step)

**Checkpoint เสร็จแล้ว:** Git commit `e01a0ece` pushed, tests ผ่าน, worktree clean ก่อน investigation

- **Step 1 — Investigation only:** เสร็จแล้ว; พบ code assumptions และปัญหา OEE join
- **Step 2 — Database Skill + Live SB23 schema:** เสร็จแล้ว; อ่าน skill, SELECT-only schema, ยืนยัน unique blocker
- **Step 3 — Final design only:** ส่งเอกสารนี้ให้ Copilot อ่าน แล้วให้ออกแบบ state model `ACTIVE/RELEASED`, Press/Mould occupancy, uniqueness (รวม reuse หลัง release), EDIT validation, shift identity mapping, legacy strategy, migration/preflight/rollback, concurrency, test plan **ยังไม่แก้โค้ด/DB**
- **Step 4 — Prepare DB change:** สร้าง migration, SELECT-only preflight, guarded rollback และ static validation tests เท่านั้น; ห้าม execute migration จนได้รับอนุมัติชัดเจน
- **Step 5 — Backend:** transactional ADD/EDIT/RELEASE + Shift-aware read/write
- **Step 6 — UI:** Shift selector, separate assignment rows, select/edit mode, safe RELEASE controls
- **Step 7 — Data/Reports:** per-shift time categories, Counter/Curing, LOGGER guide, OEE joins, regression
- **Step 8 — End-to-end validation:** cross-Lot conflict, cross-Shift reuse, release+reassign, editing with history, cross-midnight, old rows; Git commit/push หลังอนุมัติ

## 8. ข้อกำหนดการทำงานสำหรับ Copilot

- ก่อน DB work **ค้นหาและอ่าน skill**: `skill/DATABASE_ID_FIRST_DESIGN_SKILL.md` และ database contracts ที่เกี่ยวข้อง พร้อมรายงานชื่อไฟล์ที่อ่าน
- ใช้ `SB23` จริงสำหรับการตรวจสอบแบบ **SELECT-only** เท่านั้น จนกว่าจะได้รับอนุญาตชัดเจนให้ migrate; ห้ามเปิดเผย credentials
- ห้าม INSERT/UPDATE/DELETE/ALTER/DROP, migration, auto-backfill, data cleanup หรือแก้ legacy โดยพลการ
- ห้ามเปลี่ยน REJECT FINAL, Depallet, LOGGER master/bi-directional workflow, Production Lot semantics หรือ OEE formulas นอก scope
- หากพบข้อขัดแย้งของ schema, uniqueness, historical data, RELEASE behavior ให้หยุดรายงาน ไม่เลือกทางแก้เอง
- ทุก Step รายงานสิ่งที่ตรวจ/แก้, files, SQL, tests, DB effects, risk และ Git status; รายงานแบบ **quote block** ไม่ใช้ fenced code blocks ยกเว้น code/commands จริง
- **อย่า commit/push โดยไม่ได้รับคำสั่ง**

## 10. Step 4 preparation status

Migration preparation adds nullable `PressProduction.ShiftMasterID` with a foreign key to `ShiftMaster.id`, leaves existing rows NULL/unknown, replaces the legacy all-row Press/Lot unique index with an active-only Shift-aware unique index, and includes a read-only preflight plus guarded rollback. The preflight reports legacy unknown-Shift rows and existing downtime events without modifying them. The SQL files are preparation artifacts only; do not execute them against SB23 without explicit approval.

---

## 9. สรุปสั้นสำหรับเปิดบทสนทนาครั้งใหม่

> FittingMES SB23 Shift-aware Press/Mould: เพิ่ม Shift ใน ADD FITTING และแยก PressProduction record ต่อกะ; Mould active ได้เพียงหนึ่ง assignment ต่อ Production Date+Shift ข้ามทุก Lot/Press; ข้าม Shift ใช้ซ้ำได้โดยต้อง ADD ใหม่; RELEASE MOULD ยังจำเป็นสำหรับย้ายภายในกะเมื่อเครื่องเสีย และต้องรักษาประวัติ; EDIT FITTING แก้ record เดิมแยกจาก RELEASE. Migration 027 เพิ่ม ShiftMasterID แบบ nullable แต่คง legacy assignments เป็น NULL/unknown; ห้าม backfill Shift โดยเดา. ตรวจ query และ OEE ให้ไม่ถือว่า unknown Shift คือ Shift 1.

## Step 6.2 — Single-Shift Press Production Rows

The Production page now renders one row per `PressProductionID` and its
single assigned Shift. The columns are:

`Release | Shift | Press | Mould | Dispatch | Counter | Curing | Setup | ChgOver | Idle | Cleaning | Breakdown | SMDT | LOG CAL | Save`

Each row submits only its own Shift's six downtime values. The service
continues to use the established `EquipmentTimeEvent` key:
`ProductionID + EquipmentCode + ShiftID + TimeType + SourceType`.
LOG CAL imports only the matching row Shift from the LOGGER guide. It
remains a client-side replacement of the six displayed categories and
does not save until the operator presses Save.

If the row's Press/Shift identity is ambiguous because multiple assignment
episodes share the same Lot/Press/Shift, the page displays a warning and
suppresses downtime inputs and LOG CAL. The values already stored in
`EquipmentTimeEvent` are left untouched; no Shift's downtime is copied to or
counted on another episode. Migration 027 leaves legacy assignment Shift
unknown (NULL), which remains ambiguous and is not safe for downtime
attribution.
The ambiguity safeguard continues to block nonzero downtime saves for
identities without a unique assignment episode.

Released episodes remain visible with their existing RELEASE / UNDO
RELEASE behavior, and EDIT FITTING remains available for active assignment
rows. Counter, Curing, Dispatch, the selected Lot, and the existing SMDT
rules are unchanged. This UI change does not alter OEE formulas or execute
Migration 027.

## Step 7 — Preserve Unknown Shift for Legacy Assignments

Migration 027 must not assign a Shift to existing PressProduction rows.
Their `ShiftMasterID` remains NULL because historical Shift attribution is
unknown; demo-data status is not evidence of which Shift an assignment used.
Resolve Shift IDs from `ShiftMaster` only for new or explicitly edited
assignments. Do not infer a Shift from an ID, time event, or production data.

SB23 read-only review found 18 MANUAL `EquipmentTimeEvent` rows at
`ShiftID = 2` matching existing PressProduction rows. All 18 have zero
duration, and each has a matching Shift 1 natural key (18 collisions). The
preflight reports these rows and collisions. Migration 027 does not inspect
or change EquipmentTimeEvent; it only adds the nullable assignment Shift
reference and its constraints/index. The events retain their existing
natural-key identities and durations. Legacy assignments with NULL Shift
remain ambiguous, so the application must continue to warn and suppress
unsafe downtime attribution rather than treating them as Shift 1.

The guarded rollback refuses while any PressProduction row has a populated
`ShiftMasterID`; dropping the column would discard explicit assignment Shift
data entered after migration. Restore a pre-migration backup instead. The
rollback does not change EquipmentTimeEvent.
