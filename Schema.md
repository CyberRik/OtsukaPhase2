# Database Schema Documentation

---

## 1. Deal Table (`deals`)
*Manages opportunity-level information including financials and rankings*

| Column Name | Description |
|---|---|
| `customer_id` | Unique identifier for the customer |
| `deal_id` | Unique identifier for the deal |
| `sales_info` | Sales context: department, division, employee ID, etc. |
| `deal_name` | Name of the deal |
| `expected_order_date` | Expected date of order confirmation |
| `days_until_order` | Remaining days until the expected order date |
| `registered_at` | Date the record was created in the database |
| `product_category` | Product category referenced from the Product Table |
| `hw_order_revenue` | Hardware order revenue |
| `sw_order_revenue` | Software order revenue |
| `paid_order_revenue` | Paid service order revenue |
| `hw_order_gross_profit` | Gross profit from hardware orders |
| `sw_order_gross_profit` | Gross profit from software orders |
| `paid_order_gross_profit` | Gross profit from paid service orders |
| `hw_actual_revenue` | Actual hardware revenue |
| `sw_actual_revenue` | Actual software revenue |
| `paid_actual_revenue` | Actual paid service revenue |
| `hw_actual_gross_profit` | Actual gross profit from hardware |
| `sw_actual_gross_profit` | Actual gross profit from software |
| `paid_actual_gross_profit` | Actual gross profit from paid services |
| `total_order_amount` | Total order amount |
| `total_revenue` | Total revenue `= hw_actual_revenue + sw_actual_revenue + paid_actual_revenue` |
| `total_order_gross_profit` | Total gross profit from orders `= hw_order_gross_profit + sw_order_gross_profit + paid_order_gross_profit` |
| `total_revenue_gross_profit` | Total gross profit from revenue `= hw_actual_gross_profit + sw_actual_gross_profit + paid_actual_gross_profit` |
| `order_flag` | Flag indicating whether total order amount is greater than zero |
| `comment_count` | Number of comments associated with this deal |
| `rank_first_registered_at` | Timestamp when the order rank was first assigned |
| `rank_updated_at` | Timestamp of the most recent order rank update |
| `order_rank` | Current order rank: `1_Confirmed`, `2_A+`, `3_A`, `4_B`, `5_C`, `6_P`, `7_Lost`, `8_Cancelled`, `NULL` |
| `initial_order_rank` | Order rank assigned at the time of first registration |
| `days_back_from_confirmed` | Number of days counted back from the order confirmation date |

---

## 2. Order Table (`orders`)
*Manages order-level transactions including product and pricing details*

| Column Name | Description |
|---|---|
| `customer_id` | Unique identifier for the customer |
| `order_id` | Unique identifier for the order |
| `quote_id` | Unique identifier for the associated quote |
| `sales_info` | Sales context: department, division, employee ID, etc. |
| `ordered_at` | Date the order was placed |
| `shipped_at` | Date the order was shipped |
| `shipping_duration` | Number of days between order placement and shipment |
| `total_sales_amount` | Total sales amount at the slip level |
| `cancellation_penalty` | Cancellation penalty amount at the slip level |
| `product_code` | Unique product identifier |
| `manufacturer_model_number` | Manufacturer's model number |
| `product_name` | Name of the product |
| `supplier` | Supplier name or identifier |
| `contract_unit_price` | Contracted unit price |
| `evaluated_unit_price` | Evaluated unit price |
| `standard_unit_price` | Standard list unit price |
| `selling_unit_price` | Actual selling unit price |
| `cost_of_goods_sold` | Cost used to calculate gross profit |
| `gross_profit_amount` | Gross profit amount |
| `gross_profit_rate` | Gross profit margin (%) |
| `discount_amount` | Discount amount applied |
| `discount_rate` | Discount rate applied (%) |
| `requested_quantity` | Quantity requested by the customer |
| `product_major_category` | Top-level product category (e.g., PC Peripherals) |
| `product_mid_category` | Mid-level product category based on use case (e.g., Mobile Devices) |
| `product_minor_category` | Specific product type (e.g., iPad) |

---

## 3. Quote Table (`quotes`)
*Manages quote-level information including pricing and validity*

| Column Name | Description |
|---|---|
| `quote_type` | Quote type: `Product Sales` or `Maintenance` |
| `quote_id` | Unique identifier for the quote |
| `quoted_at` | Date the quote was issued |
| `quote_expiry_date` | Expiration date of the quote |
| `customer_id` | Unique identifier for the customer |
| `sales_info` | Sales context: department, division, employee ID, etc. |
| `order_flag` | Order status: `Pending` or `Confirmed` |
| `quote_amount` | Total quoted amount |
| `standard_amount` | Standard list price amount |
| `discount_amount` | Discount amount applied |
| `discount_rate` | Discount rate applied (%) |
| `product_major_category` | Top-level product category (e.g., PC Peripherals) |
| `product_mid_category` | Mid-level product category based on use case (e.g., Mobile Devices) |
| `product_minor_category` | Specific product type (e.g., iPad) |
| `similar_quote_count` | Number of times a similar product has been quoted previously |

---

## 4. Sales Activity Table (`sales_activities`)
*Tracks all customer-facing sales activities and interactions*

| Column Name | Description |
|---|---|
| `customer_id` | Unique identifier for the customer |
| `opportunity_id` | Unique identifier for the sales opportunity |
| `fiscal_year` | Fiscal year in which the opportunity was initiated |
| `fiscal_quarter` | Fiscal quarter in which the opportunity was initiated |
| `started_at` | Date the opportunity was started |
| `activity_date` | Date on which the sales activity occurred |
| `closed_flag` | Flag indicating whether the opportunity has been closed and tracking has ended |
| `activity_type` | Type of sales activity: `001_Scheduled`, `002_Daily Report`, `003_Deal`, `004_Quote`, `005_Order`, `006_Maintenance Quote`, `007_Maintenance Contract`, `008_Contract Billing`, `901_Auto-Scheduled` |
| `days_since_last_order` | Number of days elapsed since the most recent order |
| `total_order_count` | Total number of orders placed across all periods |
| `sales_info` | Sales context: department, division, employee ID, etc. |
| `business_card_info` | Business card details linked to the daily report (e.g., contact's title, department) |
| `product_major_category` | Top-level product category discussed during this activity |
| `customer_challenge` | Estimated challenges or pain points of the customer |
| `daily_report` | Sales representative's notes and records from the interaction |
| `quote_id` | Associated quote ID *(if applicable)* |
| `order_id` | Associated order ID *(if applicable)* |
| `deal_id` | Associated deal ID *(if applicable)* |

---

# How Senpai's pipeline maps to this schema

The Senpai pipeline is built **directly against these four tables** so that, once we get
real SPR access, deployment is a drop-in: replace the synthetic seed with the real export
and nothing else changes. Until then, `senpai/data/gen_seed.py` generates byte-stable
synthetic data in exactly this shape.

### Tables we mirror (canonical)
`senpai/data/seed/{deals,orders,quotes,sales_activities}.json` — field-for-field as above.

### Supplementary reference data (not part of the SPR export)
These are referenced *by* the SPR tables and would come from master data / other systems /
knowledge mining: `reps.json` (resolved from `sales_info.employee_id`), `customers.json`,
`products.json`, `playbook.json` (mined from `daily_report`), and `environments.json`
(customer IT environment — **a gap**: not present in the four SPR tables; confirm its source).

### Deal-health signals → source fields
The deterministic scorer (`senpai/health/scoring.py`) reads only real fields:

| Signal | Source field(s) |
|---|---|
| staleness | latest `sales_activities.activity_date` |
| rank stagnation | `rank_updated_at` vs `order_rank` benchmark |
| order date passed | `days_until_order` / `expected_order_date` |
| rank regression | `order_rank` vs `initial_order_rank` |
| missing decision-maker | `sales_activities.business_card_info` (title) |
| stall language | latest `sales_activities.daily_report` |
| low activity | gap in `sales_activities.activity_date` |

Report-reliability flags (`senpai/health/flags.py`) use the same fields plus `order_rank`
(optimism-mismatch: a strong rank with red health), `total_order_amount`, and
`expected_order_date`.

### `order_rank` is the spine
`1_Confirmed` = won · `2_A+ … 6_P` = live pipeline (lower number = stronger) ·
`7_Lost` / `8_Cancelled` = dead. Benchmarks and the open/won/dead sets live in
`senpai/config.py` (`RANK_BENCHMARKS`, `OPEN_RANKS`, …) so the rules stay auditable.

### Open questions for the data owner
Full `order_rank` history (not just first + latest, needed for regression) · how
`order_rank` is assigned (rep-manual vs rule-based) · `daily_report` fill-rate/length ·
`opportunity_id` ↔ `deal_id` cardinality · where customer IT-environment data lives ·
anonymization rules.

> **Note:** each deal row also carries a few legacy alias fields (`stage`, `amount`,
> `expected_close_date`, …). These are **not** part of this schema — they exist only so a
> separate, in-progress web-app experiment keeps running, and can be dropped once it migrates.