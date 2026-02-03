# GSM Strategic PRD: Tab 1 – PLAY (The War Room)

This document serves as the comprehensive functional and strategic specification for **Tab 1: PLAY**, the core engine of the **Grand Slam Matchmaking (GSM)** ecosystem.

## I. Executive Summary & Vision

*   **One-Line Pitch:** A unified ecosystem to find your next rival, track your technical climb, and build your digital athlete brand.
*   **Mission:** To become the "ATP for Amateurs" by establishing a global standard for amateur scoring and organized competitive play.
*   **Core Goal:** Minimize "Time-to-Court" by removing all friction from the matchmaking process.

## II. The "Titan" Strategic Framework

*   **Alex Hormozi (The Grand Slam Offer):** Focus on the result—finding a perfect match in 60 seconds. The "Ready to Play" button is the "Buy Now" button; matchmaking must be brainless.
*   **Mark Cuban (Scalability & Data):** Scalability is king. By keeping matches self-organized and avoiding court-ownership overhead, GSM can scale globally simultaneously.
*   **Gary Vaynerchuk (Social Arbitrage):** The "social footprint" is the oxygen for growth. Use shareable graphics and community status to drive organic attention.

## III. Functional States & Interaction Flow

Tab 1 is a dynamic state machine that adapts the UI to the user's immediate needs in the match lifecycle.

### State 1: Discovery (The Initial Hunt)

*   **Context:** Default view for users browsing for local opportunities.
*   **Interface Features:**
    *   **Map/List View:** Cards showing nearby players, their GSM Ratings (1000–4000), and distance.
    *   **The Rating Filter:** Users primarily see opponents within a **+/- 500 point range** to ensure competitive integrity.
    *   **Top Toggle:** Quickly switch between **Local Matches** (Casual/Self-organized) and **Active Leagues** (Formal Round Robin).
*   **Action:** Click **"Challenge"** to initiate a formal match request.

### State 2: Broadcasting (I Can Play)

*   **Trigger:** User taps the **"I’M READY TO PLAY"** Floating Action Button (FAB).
*   **User Selections:**
    *   **Availability:** Choose between "Today," "Tomorrow," or "Weekend".
    *   **Court Status:** "I have a court at location X" or "I am available—need a court".
    *   **The "Hard Cut-off":** Set an expiration time (e.g., 6 hours before match) to protect your schedule.
*   **Visual Feedback:** The user's profile card moves to the **top of the stack** with a high-visibility Volt Green glow and initiates a **"Live Pulse" animation** on the map.

### State 3: The Handshake (Being Challenged)

*   **Context:** A rival accepts the broadcast terms.
*   **Notification:** High-priority push notification with a 5-minute expiration timer to drive urgency.
*   **Action:** The recipient can **Accept** (confirming logistics) or **Decline**.

### State 4: Execution (Match Confirmed)

*   **The Big Shift:** The Map and Discovery list vanish. The UI focuses entirely on the upcoming event.
*   **Top Card (Logistics):**
    *   Opponent’s photo and GSM Rating.
    *   One-tap **GPS Navigation** (Google Maps/Waze) to the court.
    *   Direct **Chat link** to coordinate final details.
*   **Bottom Section (The Lab Snippet):**
    *   **"Tale of the Tape":** A radar chart comparing your stats vs. the opponent's (e.g., Serve, Stamina, Power).
    *   **AI Scouting Insight:** "Opponent's weakness: Low stamina in Set 3".

### State 5: The Ceremony (Log & Verify Score)

*   **Action:** Enabled 30 minutes after the scheduled start time.
*   **The Interface:** A tactile **Score Dial** to input set results.
*   **Verification:** Once one player logs, the other must **Confirm** or **Dispute**.
*   **Payoff:** A "Victory Animation" showing GSM points rising (e.g., +100 for a win, +50 bonus for beating a higher level).

## IV. Figma & Technical Specifications

### 1. Visual Aesthetics ("Cyber-Athletic")

*   **Color Palette:** **Deep Charcoal** background (`#0A0E12`) with **Volt Green** (`#BFFF00`) for Tennis/Winning and **Electric Blue** (`#00D1FF`) for Padel/Analytics.
*   **Typography:** Bold, condensed sans-serif for headings; high-readability clean fonts for data.
*   **The 3-Tap Rule:** Users must be able to find a match or log a result in 3 taps or less.

### 2. Interaction Feedback

*   **Broadcasting:** Your map pin pulses with a green halo to signal active status.
*   **Haptics:** Distinct vibration patterns for "Match Found" (celebratory) and "Challenge Received" (heartbeat pulse).
*   **Privacy:** Presence data on the map uses **jittered coordinates** so users' exact home locations are never exposed.

### 3. Strategic "Top-Notch" Features

*   **Ghost Pins:** If local liquidity is low, show pins for local clubs and league hubs to make the ecosystem feel alive.
*   **The Hype Share:** Immediately after verification, offer a "Share Story" button that creates a professional-grade graphic of the win for Instagram.

## V. Development Roadmap (The 6-Week Sprint)

*   **Weeks 1–2:** Waitlist growth and mapping local clubs (No coding).
*   **Weeks 3–4:** Concierge matching via WhatsApp to validate "Time-to-Match" metrics.
*   **Weeks 5–6:** Ship **PLAY V1** (Discovery list + FAB Toggle + Logistics Card) with WhatsApp deep-linking for chat.
