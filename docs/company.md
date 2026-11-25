# Halden Roasters Ltd

Halden Roasters is a fictional company. It, its customers and all of its data are invented
for this portfolio. A web search on 25 November 2026 found no coffee business of that name;
any resemblance to a real one is accidental.

## The business

Halden roasts coffee in Manchester and sells it online, mostly as subscriptions. A customer
picks one of three plans and a monthly or fortnightly delivery:

| Plan | Contents | Price to 31 Jan 2025 | Price from 1 Feb 2025 |
| --- | --- | --- | --- |
| `CLASSIC_250` | 250 g of the house blend | £11.50 / €13.50 | £12.50 / €14.90 |
| `EXPLORER_2X250` | Two rotating single origins | £21.00 / €24.50 | £22.50 / €26.50 |
| `ESPRESSO_1KG` | 1 kg espresso roast | £32.00 / €37.00 | £34.00 / €39.50 |

It also sells one-off products (beans, gift boxes, grinders, pour-over kits) to members and
to guests who check out without an account.

Customers are in the UK, Ireland, Germany and the Netherlands. UK orders are billed in GBP
and ship from the fulfilment partner's Manchester site. Since Brexit, EU orders are billed in
EUR and ship from the same partner's Hamburg site, so they avoid customs on every parcel.

## Systems

The web shop takes orders and runs subscription renewals in a nightly batch. A card processor
takes payments. A German fulfilment partner packs and ships from both sites. Customer
records live in a CRM, which replaced a spreadsheet-based system in March 2023. In 2025 the
retention team started using an experimentation platform. `docs/conventions.md` lists the
files each system sends.

## Timeline

| Date | Event | Where it shows up |
| --- | --- | --- |
| 2021 to 2022 | First customers, on the old customer system | 4,200 subscribers already active on 1 Jan 2023, with legacy IDs |
| 1 Jan 2023 | Start of the data window | First daily files |
| 13 Mar 2023 | CRM migration. Part of the legacy list is imported twice | Duplicate customers with the same `legacy_id` |
| Oct 2023 | Ops opens a week of shop exports in Excel and saves them | Phone numbers in scientific notation |
| Feb 2024 | Shop platform update changes the date format for a week | `DD/MM/YYYY HH:MM` timestamps |
| 18 Mar 2024 | Shop export times out; the day is sent again | Truncated file plus a `_resend` |
| 20 May 2024 | Fulfilment partner corrects a week of delivery dates | `_v2` file |
| 1 Jul 2024 | Card processor moves to schema v2 | Columns reordered, `net_amount` added |
| 12 Sep 2024 | Card processor skips a day's file | Two days in one file |
| Q3 2024 | Finance finds BI revenue does not match the processor | Starts project 1 |
| 11 to 24 Nov 2024 | Hamburg site staffing problem | Late EU deliveries |
| Q4 2024 | Marketing questions the customer count | Starts project 2 |
| Q4 2024 | The monthly KPI pack is still built by hand | Starts project 3 |
| 1 Feb 2025 | Price increase of 6.3% to 10.4%, depending on plan and currency | Cancellations rise from February, peaking in March |
| Q1 2025 | Retention team asks who is at risk and whether an offer pays | Starts project 4 |
| 1 to 30 Apr 2025 | Retention offer test `RET-2025-04`: 30% off the next three boxes | Assignment events, `RET30` orders |
| 9 to 11 Apr 2025 | The experiment logger drops events | Fewer treatment events than expected |
| 30 Jun 2025 | End of the data window | Last daily files |
