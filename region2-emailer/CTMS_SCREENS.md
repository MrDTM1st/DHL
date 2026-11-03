# CTMS screens, as learned live (03/11/2026)

What Book and the to-do Run work with, read through the Access Bridge and pictured on the work PC on 03/11 with
Delali at the keyboard. One unbooked ad hoc (wheelsets, one line) was opened, read tab by tab, and closed without
saving. Nothing was changed. Values seen are not kept here, only how each screen is built and how it behaves.

Coordinates: **Access Bridge "screen" points** (what `at` holds) unless marked *picture*. On the work PC's window as it
sat that day, picture = screen - (6, 98); the batch's anchor works that out each run, so recipes keep using picture
points and Access Bridge points side by side.

## What a read costs (the reason Book is slow)

| Screen up | Things read | Seconds (reader's own count) |
|---|---|---|
| Order Summary | 325 | 1.87 - 1.96 |
| An order card (any tab) | 385 - 583 | 1.95 - 2.20 |
| Planning | 857 - 932 | 2.81 - 3.07 |

About **1.5 s of every read is a fixed wait** (`ctms_jab.Api.__init__`: `pump(1.5)` while the Access Bridge finds
Java), paid again on every read because each read is a fresh 32-bit Python. The walk itself is 0.4 - 1.5 s and grows
with what is on the screen; Planning's manifest tree is most of Planning's. A one-line Book reads 12-14 times (counted
on tests/test_ctms_book.py's FakeCtms), so reads alone are 30-45 s on the real PC.

Fixed waits seen in the existing recipes, same day: Orders menu to Order Search 9.5 s (8.0 s one step), Planning open
9.5 s (8.0 s one step), an order search 6.0 s (4.0 s one step).

## Order Summary (C-TMS Modules > Order Management > Orders)

- **"up to" limits every search.** It defaults to a day or so ahead (04/11/26 on 03/11). An order delivering later is
  simply not listed, whatever Customer Ref says: the wheelsets (10/11) and 7116527 (13/11) only came up with "up to"
  moved past their day. `ctms_orders.search()` never sets it, so the look-up, the split and the to-do update find
  nothing for later orders and sit out their waits. Its box: Access Bridge `text 'up to'`, picture (243,164); typed as
  dd/mm/yy over what it holds.
- Lines read by name as before (`Enter value for : SCHED_NAME / EXTERNAL_REF / STATUS / DELIVERY_TYPE_ID /
  EARLY_AVAIL / LATE_DEL`). An ad hoc's line is its ref whole, no -1-1.
- Opening a line: double-click its Status cell, picture (267,238), with the search card closed.

## The order card ("Order details for <OMS ref>")

Header: `Status Required`, `Oms Ref`, `Booking Ref`, `Booked In` (check box), `Customer Ref`, `Del Point Ref`.
Buttons at the foot: New Order, Gen Items, View Info, **Save**, **Close**, Re-book, Send Ord Msg, Non Conformance.

Tabs (`page tab`, by name): Detail, Order Items, Add Refs, Add Detail, LOC Detail, MTM Info, Audit, Audit Archive,
Finance, Services, Non Conformance, Payments Savings (disabled), Trip Detail, Hazardous Data.

### Detail
- `Cost Centre`, `Customer`, `Schedule`, `Group Name`, `Collect From` / `Deliver To` (location ids; the names beside
  them read-only), `Temp Combo`, **`Veh Type` (combo box)**.
- `Collect Times` / `Delivery Times`: four text boxes a row (from date, from time, to date, to time); only the first of
  each row is named, the rest are nameless and told by where they sit.
- Standard times / Collection Time Target / Delivery Time Target / Open Window (radio buttons).
- `Service Level`, Business Type (a combo named `1` and its words read-only beside it, e.g. "Strategy 1 - Flats & Hiabs").
- **The product grid at the bottom**: columns `Product Type`, `DU Type`, `Qty`, `Weight`, then Cases, RPE, Packed,
  Despatched, Delivered...; five rows, the first editable. **This Product Type is the right one** (his rule).
- `Special Instructions Multiline`.

### Order Items
- Grid: `Identifier Required` (read-only here), `Product`, `Aka Code`, `Item Description`, Factor, Lifts, Stack,
  **`Ordered`**, To Deliver, Delivered, Diff, **`Weight`**, Volume, Location. Totals row underneath.
- Buttons **Create** and **Edit/Delete** (the item), Layout combo; a Reason grid below with its own (disabled)
  Create / Edit/Delete.

### Create, Edit or Delete Order Item (Edit/Delete opens it, a window of its own)
- `Oms Ref Required`, **`Product` (combo box)**, `Du Type`, **`Identifier Required`**, `Aka Code`, Pallet ID,
  `Description`, Factor, Lifts, Stack, **`Ordered`**, To Deliver, Delivered, **`Weight`**, Volume, Units, Pack Quantity,
  WCS Loc, Length, Width, Height.
- Buttons: **Save**, New, Clear, **Delete** (never pressed), **Exit**. Exit with nothing changed asks nothing.
- **Ctrl+L in Identifier** opens **"Product Items"**, a list of values: `Find` pre-filled with Identifier + `%`, its rows
  read as labels `Item_Id:<id>\tItem_Description:<words>` (the picked one `selected`), the status bar "Choices in list:
  N", buttons `Find ALT F`, `OK ALT O`, `Cancel ALT C`. Cancel leaves Identifier as it was.
  (Ctrl+L reaches Java: the bridge only refuses it on web pages, where Edge would take it for the address bar.)

### Trip Detail
Not the product: the trips the order is on - Sched, Trip ID, Carrier ID, Trip Status, Trip Cost, Load Location,
Consignee, Unload Location, Consignor, Exp/Act Dep, Exp/Act Arr. Empty while unscheduled; after a booking it is a
second place to see the manifest the order went on.

### Services
Grid: Service Id, Name, Qty, Value, Adjusted Value, Charge Revenue, Inherited (combo); buttons New, Save, Edit, Delete.
The first column's cell is named `Services tab page null`.

### LOC Detail
Collection side and delivery side: Location Id, Location Name, Address Lines, Town, Country, Postcode (all read-only),
the contact line under each (read-only, each with its own **Edit**), View Location Address, Message Medium (combo).

### Add Detail
`Order`, **`Delivery Type`** (its `v` button opens the list), Original From, Final To, Interface Id, Src Sys,
**`Cont Wt`**, **`DUs`**, `Last Error` (contract / tariff found or not), STD Cost Data, Revenue Data.

## Planning

- Tree: `Sched` combo, Search box; manifests as labels "dd/mm/yy HH:MM MAN-... (STATUS)".
- The well's bar: layout combo ("1: Delali"), **Sched From**, **To**, Status (UNSCHEDULED), Current, `#`, New Order,
  **Order Filters**. 15 rows a page; columns Cust Ref, Booking Ref, From Loc, From Post, To Loc Name, To Postcode, To
  (region), Fr, Collect, Deliver, Del Type, Weight, DU's, Product Type, Vehicle, Length, Di.
- **Sched From's list only runs the week up to today** (261028 - 261103 on 03/11): it cannot be put on a future day, so
  the well cannot be narrowed to one future day that way. Seven Downs ran it off its end and CTMS said **"A schedule
  must be selected."** (a Forms alert; OK put it back as it was). To's list runs from today forward, a day a row, the
  current one `selected` - read it before pressing anything.
- **Order Filters** (panel): From Plan Reg (two combos), To Plan Reg, Postal Reg (disabled) with From/To, Postcode with
  From/To, Location with From/To/Either, Weight / Volume / RPE each with > < =, Curr Loc; Refresh, Clear, **Advanced
  Filters**. Its X: picture (437,404) where it sat.
- **Advanced Order Filters** (window): Delivery Type (All), Service Type (All), Order Type, Reason Code, Transport Mode,
  Collection Route, Delivery Route, Customer, **Business Type** with **Inc Nulls?**, Booking Status, Multi Product Types,
  Show All Orders / Show Urgent Orders / Show Late Orders / Not Booked In, Auto Processed: PCL, WS, Van Fleet,
  Carrier; Search, Close.

## What the Access Bridge does not hand over

- **A combo box's value.** Veh Type, Product, every filter combo, Business Type's combo, Layout - all read as `''`
  even when the picture shows a value. The reader skips a closed drop-down's rows on purpose (one of Planning's holds
  thousands), and the box's own text is not given. Today Veh Type is told by dark pixels in its box
  (`ctms_orders.veh_filled`). The Access Bridge can give a combo's selected item directly
  (`getAccessibleSelectionFromContext`), without walking its rows - not tried yet.
- Things off the screen come with `at` of -1s (the list of values' rows do too, but are still read with their words).
