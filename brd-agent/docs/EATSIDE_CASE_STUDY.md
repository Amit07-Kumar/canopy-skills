# Eatside POS Integration & Menu Sync — Case Study

## 1. The Scenario
**Eatside** is a rapidly growing food delivery platform. To improve restaurant partner retention and reduce order errors, Eatside is building a direct integration with major Point-of-Sale (POS) systems (Toast, Square, Clover). 

Instead of restaurants manually typing Eatside orders from a tablet into their POS, the orders will be injected directly into the kitchen display. Additionally, the restaurant's menu (prices, descriptions, and out-of-stock items) needs to sync back to the Eatside app.

## 2. The Stakeholders
- **Sarah Jenkins (Product Manager)**: Owns the project. Her primary goal is to launch by the April 1st marketing deadline.
- **David Chen (Lead Engineer)**: Owns the technical architecture. His primary concern is system stability and preventing database crashes from too many API calls.
- **Elena Rodriguez (Restaurant Ops)**: Represents the restaurant partners. Her primary concern is preventing canceled orders caused by out-of-stock items still showing as available on the app.
- **Mike O'Connor (Customer Support)**: Manages the support agents. His primary concern is reducing the massive volume of support tickets related to missing items.
- **Alex Thorne (Finance Director)**: Manages the money. His primary concern is preventing refund fraud.

## 3. The Core Conflicts (What the Agent Solves)

### Conflict 1: Menu Sync Frequency (Technical vs Operational)
- **The Problem**: Engineering (David) wants to sync menus every 5 minutes to save server load. Restaurant Ops (Elena) says a 5-minute delay during the lunch rush means popular items sell out, but customers keep ordering them for 5 more minutes, leading to angry customers and canceled orders.
- **The Resolution**: The agent identifies this conflict and suggests a hybrid approach: Use real-time webhooks *only* for inventory status (in-stock/out-of-stock), and use the 15-minute batch process for heavy data like images and descriptions.

### Conflict 2: Refund Automation (Process Disagreement)
- **The Problem**: Customer Support (Mike) wants to automatically refund users for missing items because his agents are wasting 40% of their time on $12 refunds. Finance (Alex) refuses to automate refunds because fraud rings exploit automated systems.
- **The Resolution**: The agent helps negotiate a threshold. Refunds under $50 are automated. Refunds $50 and over go to a manual review queue. Additionally, a "3-strike" fraud rule is implemented: if a user requests more than 3 refunds in a month, automation is disabled for their account.

### Conflict 3: POS Vendor Certification (Timeline Conflict)
- **The Problem**: PM (Sarah) has a hard launch date of April 1st. Engineering (David) discovers that Toast POS requires a 4-week certification process, meaning they won't be ready until April 15th.
- **The Resolution**: The agent suggests a phased rollout. Launch on April 1st with Square and Clover, and announce Toast as "Coming Mid-April".

## 4. How to Demo This Case

1. **Dashboard View**: Show the overall health of the "Eatside POS Integration" project. Point out the 3 active conflicts and the stakeholder sentiment (Ops and Finance are unhappy).
2. **Knowledge Graph**: Show how the requirements connect. Click on "Real-time Inventory" (R2) to show how it's demanded by Ops but blocked by Engineering due to load.
3. **Playground - Email to BRD**: 
   - Select the email "Menu Sync Architecture Proposal".
   - Generate the BRD. Show how it initially captures the "5-minute batch" requirement.
4. **Playground - Chat Integration**:
   - Select the chat "POS Integration Kickoff & Architecture".
   - Click "Integrate Chat into BRD".
   - Show the diff: The agent intelligently replaces the "5-minute batch" requirement with the "Hybrid Webhook" compromise discussed in the chat.
5. **Playground - Refund Policy**:
   - Do the same for the Refund Policy email and chat, showing how the $50 cap and 3-strike rule are automatically added to the BRD.
