# SB2/3 FittingMES -- Depallet Change Summary

## Purpose

ปรับ Concept หน้า **DEPALLET ของ SB2/3** จากเดิมที่สามารถป้อน Lot แกะ
(Depallet Lot) แบบ free text ให้เปลี่ยนเป็นการเลือกจาก **Production Lot
ที่เคยผลิตจริงเท่านั้น** และต้องควบคุมยอดคงเหลือในห้องบ่ม (Remaining Curing Qty)
ของแต่ละ Production Lot

หลักการคือ Production Lot หนึ่ง Lot สามารถถูกนำมาแกะได้หลายวัน/หลายครั้ง
จนกว่ายอดในห้องบ่มจะหมด

ตัวอย่าง:

-   ผลิตเข้า Curing = 3,000 pcs
-   วันแรกแกะ = 500 → Remaining Curing = 2,500
-   วันถัดมาแกะ = 2,000 → Remaining Curing = 500
-   ครั้งต่อไปแกะได้สูงสุด = 500
-   เมื่อ Remaining Curing Qty = 0 ยังให้เห็น Lot ในรายการ แต่ **disable /
    สีเทา และเลือกไม่ได้**

------------------------------------------------------------------------

## 1. Production Date กับ Depallet Date

ปัจจุบัน Date ด้านบนใช้ร่วมกันระหว่างหน้า Production / Usage / Depallet ฯลฯ

สำหรับหน้า **DEPALLET** ให้ถือวันที่ที่เลือกด้านบนเป็น **Depallet Date / วันที่แกะ**

ไม่ต้องเปลี่ยน Concept navigation วันที่ที่ทำไว้แล้ว

------------------------------------------------------------------------

## 2. เปลี่ยนการเลือก Depallet Lot

เลิกการป้อน `Lot No.` แบบ free text

ให้สร้าง Frame ด้านบนสำหรับเลือก Production Lot ที่จะนำมาแกะ ลักษณะคล้าย
Excel/ตาราง และรองรับการสร้าง Depallet หลาย Lot ในวันเดียวกัน

ลำดับการเลือก:

### Step 1 -- Product Family

Dropdown แรกเลือกกลุ่มครอบ เช่น 4 Family ที่ระบบมีอยู่ เช่น:

-   Prestige
-   ครอบ
-   Oriental
-   Family อื่นตามข้อมูลจริงในระบบ

**ห้าม hard-code ถ้าระบบมี master / ProductFamily อยู่แล้ว
ให้ใช้ข้อมูลจริงของระบบ**

### Step 2 -- Product / Material

หลังเลือก Product Family แล้ว Dropdown ที่สองแสดงเฉพาะสินค้า/ครอบที่อยู่ใน Family
นั้น

ควรแสดงข้อมูลที่ช่วยให้พนักงานรู้ว่าเป็นสินค้าอะไร เช่น:

`ProductCode | MaterialName`

### Step 3 -- Production Lot

หลังเลือก Family + Product แล้ว Dropdown ที่สามจึงแสดง Production Lot
ที่เคยผลิตจริงของสินค้านั้น

เรียง:

1.  `ProdDate DESC`
2.  Running No / ProductionID ที่เหมาะสม `DESC`

แสดงข้อมูลประกอบอย่างน้อย:

-   Lot No.
-   Production Date
-   Production Qty / Curing Qty
-   Already Depallet Qty
-   Remaining Curing Qty

Lot ที่ `RemainingCuringQty = 0`:

-   **ยังต้องแสดงใน list**
-   แสดงเป็นสีเทา
-   disabled
-   เลือกไม่ได้

------------------------------------------------------------------------

## 3. CREATE DEPALLET LOT

เมื่อเลือก Family → Product → Production Lot ครบแล้ว ให้มีปุ่มประมาณ:

`CREATE DEPALLET LOT`

เมื่อกด ให้เพิ่ม Production Lot นั้นลงใน Frame/Table **DEPALLET LOTS** ด้านล่าง

สามารถทำซ้ำเพื่อเพิ่มหลาย Production Lot ที่ต้องการแกะในวันนั้นได้

ไม่ควรสร้าง Production Lot ใหม่ และไม่ควรรับ Lot ที่ไม่มีอยู่ใน ProductionLot

ต้องผูกด้วย `ProductionID` เป็นหลัก ไม่ใช่อาศัย LotNo string อย่างเดียว

------------------------------------------------------------------------

## 4. DEPALLET LOTS Table

Frame ที่สองเป็นตารางคล้าย Excel หนึ่ง Row ต่อหนึ่ง Depallet Lot

แต่ละ Row ควรมีอย่างน้อย:

-   Select row
-   Lot No.
-   Shift
-   Remaining Curing Qty
-   Depallet Qty
-   Good Qty
-   Reject Qty
-   Remark

`Remaining Curing Qty` เป็นข้อมูลแสดงผล ไม่ใช่ช่องให้ผู้ใช้แก้เอง

เมื่อเลือก Row ใด ให้ Row นั้นเป็น Active Row และ **REJECT DETAIL
ด้านล่างเปลี่ยนไปแสดง Reject ของ Depallet Lot ที่เลือก**

ต้องสามารถสลับไปมาระหว่างหลาย Lot โดยค่าที่กรอกไว้ของแต่ละ Lot ไม่หาย

------------------------------------------------------------------------

## 5. Remaining Curing Qty

ต้องคำนวณจากยอด Production จริง เทียบกับยอดที่เคย Depallet ไปแล้วทุกวัน

Concept:

``` text
ProductionQty
    = จำนวนที่ผลิต/เข้าห้องบ่มของ Production Lot

DepalletQtyTotal
    = SUM(Depallet.DepalletQty) ของ ProductionID นั้นทั้งหมด

RemainingCuringQty
    = MAX(ProductionQty - DepalletQtyTotal, 0)
```

Production Lot สามารถมี Depallet records หลายวันได้

**อย่าคำนวณเฉพาะ Depallet Date ปัจจุบัน** เพราะ Remaining ต้องเป็นยอดสะสมข้ามวัน

------------------------------------------------------------------------

## 6. SQL View ที่เตรียมไว้

มี/กำลังใช้ View:

`dbo.vw_DepalletCuringBalance`

จุดประสงค์คือเป็น source กลางสำหรับ Production Lot selection และ Remaining
Curing Qty

ข้อมูลที่ View ควรมี/มีลักษณะประมาณ:

-   ProductionID
-   ProdDate
-   Shift
-   PlanName
-   ProductFamily
-   MaterialCode
-   MaterialName
-   ProductCode
-   LotPrefix
-   LotNo
-   ProductionQty
-   DepalletQtyTotal
-   RemainingCuringQty
-   DepalletCount
-   FirstDepalletDate / LastDepalletDate (ถ้ามี)

จากผลทดสอบ SQL ก่อนหน้า พบตัวอย่างกรณี:

-   ProductionQty = 1790
-   DepalletQtyTotal = 1910
-   RemainingCuringQty = 0

ดังนั้น View ต้อง clamp Remaining ไม่ให้ติดลบ

``` sql
CASE
    WHEN ProductionQty - DepalletQtyTotal > 0
        THEN ProductionQty - DepalletQtyTotal
    ELSE 0
END
```

**Application ควรใช้ View นี้แทนการเขียน calculation ซ้ำหลายจุด หาก
schema/view ปัจจุบันตรงตามนี้**

------------------------------------------------------------------------

## 7. Validation ตอนกรอก Depallet Qty

นี่เป็น Requirement สำคัญ

เมื่อผู้ใช้ป้อน `Depallet Qty` ของ Lot:

``` text
DepalletQty <= RemainingCuringQty
```

ถ้าผู้ใช้ป้อนเกิน Remaining:

ตัวอย่าง:

``` text
Remaining = 500
User enters = 800
```

ระบบต้อง:

1.  แจ้ง Alarm/Warning ว่าจำนวนที่ป้อนเกินยอดคงเหลือในห้องบ่ม
2.  Auto-correct ค่า `Depallet Qty` จาก 800 → 500
3.  ไม่อนุญาตให้บันทึกยอดเกิน Remaining
4.  Backend ต้อง validate ซ้ำอีกครั้ง ไม่พึ่ง JavaScript/UI อย่างเดียว

ดังนั้นแม้ request ถูกยิงตรงเข้า API ก็ต้องไม่สามารถสร้างยอดเกิน Remaining ได้

------------------------------------------------------------------------

## 8. Concurrency / Recheck ก่อน Save

Remaining ที่แสดงตอนเปิดหน้าอาจเปลี่ยนได้หากมีอีก client บันทึก Depallet

ดังนั้นก่อน INSERT/UPDATE จริง ให้ backend query Remaining ล่าสุดอีกครั้ง

ห้ามเชื่อค่าจาก browser เพียงอย่างเดียว

ถ้ายอดใหม่เกิน Remaining ล่าสุด ให้ใช้กฎเดียวกันคือ reject/correct ตาม behavior
ที่กำหนด และห้ามทำให้ cumulative Depallet เกิน Production Qty

------------------------------------------------------------------------

## 9. REJECT DETAIL

Reject Detail ยังคงผูกกับ Depallet Lot/Row ที่เลือก

Layout ปัจจุบันมี Reject codes เช่น:

-   R01--R10
-   R11--R20
-   R21--R24
-   R99

ปรับ UI เพิ่มเติม:

### ลดความกว้าง Reject Reason

ปัจจุบัน column `Reject Reason` กว้างเกินข้อความมาก ให้ลดลงเพื่อใช้พื้นที่หน้าจอให้กระชับ

### เพิ่ม Qty/Day

ปัจจุบันมี:

`Code | Reject Reason | Qty`

ให้เพิ่ม:

`Code | Reject Reason | Qty | Qty/Day`

ความหมาย:

-   **Qty** = Reject ของ Depallet Lot/Row ที่กำลังเลือกอยู่
-   **Qty/Day** = SUM Reject code เดียวกันของ **ทุก Depallet Lot ใน
    Depallet Date ที่เลือก**

ตัวอย่าง:

``` text
Lot A R02 = 10
Lot B R02 = 20
Lot C R02 = 5

เมื่อเลือก Lot B:
Qty     = 20
Qty/Day = 35
```

`Qty/Day` เป็น display/summary ไม่ใช่ช่องให้แก้โดยตรง

------------------------------------------------------------------------

## 10. Reject Validation เดิมต้องคงอยู่

ยังต้องรักษา logic ความสัมพันธ์:

``` text
RejectQty = SUM(Reject Detail ของ Lot)
```

และ validation/behavior เดิมของ:

-   Depallet Qty
-   Good Qty
-   Reject Qty
-   Classified Reject
-   Difference
-   SAVE DEPALLET
-   RELOAD SELECTED LOT

ห้ามทำให้ behavior เดิมที่ใช้งานได้เสีย

------------------------------------------------------------------------

## 11. Database Tables ที่เกี่ยวข้อง

จาก schema ที่ตรวจสอบแล้ว มีอย่างน้อย:

### dbo.ProductionLot

Primary key:

`ProductionID bigint`

มีข้อมูล เช่น:

-   ProdDate
-   Shift
-   PlanName
-   MaterialCode
-   MaterialName
-   ProductCode
-   LotPrefix
-   LotNo
-   ProductFamily
-   ฯลฯ

### dbo.ProductionData

ผูกกับ ProductionLot ผ่าน:

`ProductionID`

มี:

-   CounterQty
-   CuringQty
-   ProductionStart / ProductionEnd
-   Remark
-   ฯลฯ

Production Qty/ยอดเข้าห้องบ่มควร derive จากข้อมูล Production ที่ระบบใช้อยู่จริง
โดยต้องตรวจ implementation ปัจจุบันก่อนเปลี่ยน

### dbo.Depallet

มี:

-   DepalletID
-   ProductionID
-   DepalletDate
-   Shift
-   LotNo
-   ProductFamily
-   ProductCode
-   MaterialCode
-   MaterialName
-   DepalletQty
-   GoodQty
-   Remark
-   CreatedAt
-   UpdatedAt

และมี FK:

`FK_Depallet_ProductionLot`

ดังนั้น Concept ใหม่ควรใช้ `ProductionID` เป็นตัวเชื่อมหลัก

### dbo.DepalletReject

ผูกกับ Depallet record และเก็บ reject detail

------------------------------------------------------------------------

## 12. Compatibility กับข้อมูลเก่า

มี Depallet record เก่าบางรายการที่ ProductFamily อาจเป็น NULL แต่มี
`ProductionID`

อย่าทิ้ง record เก่าเพียงเพราะ ProductFamily ใน Depallet เป็น NULL

ให้ join กลับไปหา `ProductionLot` ด้วย `ProductionID` เพื่อใช้ข้อมูล
master/production ที่ถูกต้อง

------------------------------------------------------------------------

## 13. สิ่งที่ห้ามเปลี่ยนโดยไม่จำเป็น

การแก้ครั้งนี้เน้น **DEPALLET UI + Production Lot selection + Curing balance +
validation**

อย่าเปลี่ยนโดยไม่จำเป็น:

-   Production calculation
-   Production save
-   Usage
-   PROD API
-   REJECT API
-   Navigation date behavior ที่เพิ่งแก้และ test ผ่านแล้ว
-   Database schema หาก View/ตารางเดิมรองรับได้
-   API behavior อื่นที่ไม่เกี่ยวข้อง

ก่อนแก้ให้ inspect implementation ปัจจุบันก่อน และแก้แบบ minimal scope

------------------------------------------------------------------------

## 14. Tests ที่ควรเพิ่ม

อย่างน้อยต้องครอบคลุม:

1.  แสดงเฉพาะ Production Lots จริง
2.  Family → Product → Lot cascading selection ถูกต้อง
3.  Lot sorting ใหม่ไปเก่า
4.  Remaining \> 0 เลือกได้
5.  Remaining = 0 ยังแสดงแต่ disabled
6.  Production Lot เดียว Depallet ได้หลายวัน
7.  cumulative Depallet ถูกต้อง
8.  กรอก Depallet Qty เกิน Remaining → warning + auto clamp
9.  backend ป้องกัน overshoot
10. หลาย Depallet Lots ในวันเดียวกัน
11. Active row เปลี่ยน Reject Detail ถูก Lot
12. เปลี่ยน row แล้วค่าที่กรอกไม่หาย
13. Reject Qty/Day รวมทุก Lot ของวันถูกต้อง
14. historical Depallet ที่ ProductFamily NULL ยังทำงานผ่าน ProductionID
15. existing Depallet save/reload behavior ไม่ regression
16. date navigation tests เดิมยังผ่าน

------------------------------------------------------------------------

## Acceptance Example

Production Lot:

``` text
LotNo: B006690902
ProductionQty: 3000
```

History:

``` text
2026-09-14 DepalletQty = 500
2026-09-16 DepalletQty = 2000
```

Expected:

``` text
DepalletQtyTotal   = 2500
RemainingCuringQty = 500
```

ถ้าวันที่ 2026-09-18 ผู้ใช้เลือก Lot นี้และกรอก:

``` text
DepalletQty = 800
```

Expected UI:

``` text
Warning: Depallet Qty exceeds Remaining Curing Qty (500)
DepalletQty automatically becomes 500
```

หลัง Save:

``` text
DepalletQtyTotal   = 3000
RemainingCuringQty = 0
```

Lot นี้ยังปรากฏใน Production Lot dropdown/list แต่:

``` text
disabled = true
display = gray
```

และไม่สามารถสร้าง Depallet เพิ่มได้อีก

------------------------------------------------------------------------

## Implementation Direction

ให้เริ่มจาก inspect code/schema ปัจจุบันก่อน แล้ว reuse
`dbo.vw_DepalletCuringBalance` และ `ProductionID` ให้มากที่สุด

เป้าหมายสุดท้ายคือ:

**Production Lot → Curing inventory → partial Depallet over multiple
days → cumulative balance → zero balance disabled**

โดยยังรักษา Depallet/Reject workflow เดิมที่ใช้งานได้ทั้งหมด
