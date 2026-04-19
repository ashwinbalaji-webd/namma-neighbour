A **Horizontal Hyperlocal Marketplace**—a "Shopify meets Amazon" specifically for gated communities. Whether it’s a boutique organic farm, a home baker, a high-end electronics reseller, or the local Kasimedu fisherman, the platform remains the same. 

The app becomes a **Community Utility**, where the "What" can change daily, but the "How" (Consolidated Delivery + Unified Payments) remains the constant.

Here is the **Master PRD** for **NammaNeighbor**, designed to be a completely open but verified marketplace.

---

# PRD: NammaNeighbor (v2.0)
**The Ultimate Community-Commerce & Fintech Platform**

---

## 1. Product Vision
To create a decentralized marketplace where any verified seller can reach high-density residential clusters through a consolidated logistics and payment ecosystem, replacing fragmented WhatsApp buying with a professional, secure platform.

---

## 2. Key Modules

### I. The Seller "Self-Serve" Portal
Instead of a curated list, this is an open onboarding system.
* **Product Agnostic Listing:** Sellers can upload anything—Seafood, Flowers, Organic Veggies, Home-cooked meals, Handcrafted decor, etc.
* **Inventory & Slots:** Sellers define their "Drop Window" (e.g., *"Available for Tuesday 7 AM delivery"*).
* **Dynamic Catalog:** Support for "Flash Sales" (e.g., *"Only 10kg of Organic Mangoes available today"*).

### II. Verification & Trust Layer (The "Gatekeeper")
Since anyone can register, the platform must protect the community.
* **Document Vault:** Mandatory upload of Govt ID, GST/FSSAI (if applicable), and Bank details.
* **Logistics Audit:** Sellers must specify if they have their own delivery fleet or if they require **NammaNeighbor Pick-up**.
* **Community Vetting:** New sellers are marked "New" until they complete 5 deliveries with a $>4.5$ star rating.
* **Escrow System:** Payment is held by the platform and only released to the seller after the "Delivery Window" closes without disputes.

### III. The "One-Go" Fintech Layer
* **Unified Billing:** One monthly statement for the resident.
    * **Fixed Costs:** Rent + Society Maintenance.
    * **Variable Costs:** Total of all marketplace purchases made that month.
* **Automated Split:** Backend logic to route money to:
    1.  **Landlord** (Rent)
    2.  **Society Association** (Maintenance)
    3.  **Multiple Individual Sellers** (Marketplace orders)
    4.  **NammaNeighbor** (Platform fee/Commission)

---

## 3. Functional Requirements

| Feature | User (Resident) | Seller (Vendor) |
| :--- | :--- | :--- |
| **Onboarding** | Join via Community Invite/Location. | Register via KYB + Logistics check. |
| **Discovery** | Browse by "Today's Drops" or "Weekly Subscriptions." | Create listings with photos, price, and "Drop Date." |
| **Ordering** | Pre-order for specific delivery windows. | View "Consolidated Order Sheet" for each community. |
| **Payments** | Pay Rent + Maint + Orders in one click. | Track "Pending Payouts" and "Settled Funds." |
| **Logistics** | Real-time notification when the "Community Van" enters the gate. | Label orders by Community/Tower/Unit for easy sorting. |

---

## 4. Logistics: The "Micro-Hub" Strategy
To handle "anything" (from heavy groceries to fragile flowers), the logistics flow is:
1.  **Seller Preparation:** Seller packs items individually, labeled with a QR code (Resident Name/Tower/Unit).
2.  **Consolidation:** * *Self-Deliver:* Seller drops the batch at the community gate/lobby.
    * *Platform-Deliver:* NammaNeighbor truck picks up from multiple sellers and brings them to the community.
3.  **The "Last 100 Meters":** One person (NammaNeighbor Partner) takes the consolidated trolley to all towers, clearing security once.

---

## 5. Trust & Validation Workflow (Step-by-Step)
1.  **Sign-up:** Seller enters details.
2.  **Validation:** System checks for duplicate IDs and valid bank accounts.
3.  **Physical/Digital Audit:** For food, FSSAI is verified via API. For others, a video-call "Store Tour" or sample delivery is required.
4.  **Logistics Tiering:** * *Tier A:* Seller has their own bike/van (Trusted to deliver to gate).
    * *Tier B:* Seller uses NammaNeighbor (Must have goods ready at their location for pickup).
5.  **Performance Penalty:** If a seller misses a "Drop Window" twice, they are delisted.

---

## 6. Business Logic (The Revenue Model)
* **Commission:** 5–10% on marketplace sales.
* **SaaS Fee:** Small convenience fee for automated Rent/Maintenance processing.
* **Logistics Fee:** If the seller uses the NammaNeighbor delivery fleet.

---

## 7. Success Metrics
* **Marketplace Breadth:** Number of unique categories sold per month.
* **Consolidation Ratio:** Average number of orders delivered per single gate entry (Goal: $>15$).
* **Payment Stickiness:** % of residents who pay their Rent/Maint via the app consistently.

---

### The Big Advantage
By making it "anything," we aren't just a grocery app. You are the **Infrastructure**. If a resident wants a specific brand of organic oil or a special South Indian snack that isn't on Blinkit, they tell the seller, the seller lists it on NammaNeighbor, and it arrives in the morning "Community Drop."