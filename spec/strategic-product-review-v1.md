# GSM — Grand Slam Matchmaking

## Strategic Product Review

From Code to Product: MVP Scope, Team, Timeline & Go-to-Market

Prepared for Ignatios Charalampidis, Product Owner

March 2026

**CONFIDENTIAL**

## 1. Executive Summary

This document evaluates GSM (Grand Slam Matchmaking) from the perspective of a CEO and product leader assessing a pre-launch sports startup. It covers four areas: product UX critique, MVP scoping, team structure, and a phased timeline from code to users.

GSM is positioned to serve a real and growing market. Racket sports participation is surging globally, with padel alone growing at a 13%+ CAGR. The closest incumbent, Playtomic, raised $70M in March 2025 and has 4.7M users, but their moat is court booking infrastructure, not player intelligence. GSM attacks from a fundamentally different angle: the scoring standard and competitive identity layer for amateur players.

| The One-Line Pitch |
| :---- |
| GSM is the ATP ranking system for amateur racket sports. We turn every casual match into a competitive data point that makes players better, keeps them engaged, and creates a scoring standard no one else owns. |

| Overall Assessment |
| :---- |
| The engineering foundation is impressive for this stage. You have a fully specced 4-tab architecture, a working backend with a sophisticated state machine, Firebase Auth implemented, and 44 GitHub issues scripted for Tab 3 alone. The gap is not technical; it is the distance between this codebase and a product people can actually download, use, and tell their friends about. This review is about closing that gap. |

## 2. How the App Looks: UX & Design Critique

### 2.1 What Works Well

* **The state machine architecture is excellent.** A 9-state FSM for Tab 1 means the UI always reflects reality. This is a mature engineering decision that will prevent the state-sync nightmares that plague competitors.

* **The Cyber-Athletic design language is distinctive.** Dark mode with Volt Green (#BFFF00) and Electric Blue (#00D1FF) creates a premium, aspirational identity. This stands out against Playtomic's generic white-and-teal palette.

* **Cross-tab data integration is a hidden superpower.** Match results flowing into journals, feeding skill DNA, powering scouting reports, and surfacing in the social feed creates a compounding value loop that rewards continued use.

* **The 'Time-to-Court' obsession is the right north star.** Framing everything around reducing friction to play is the correct product instinct for a matchmaking app.

### 2.2 What Needs to Change

#### A. The Map Is a Liability at Launch

Your Discovery state shows a map with pulsing green pins. This looks incredible in a mockup with 20 active players. At launch in Athens with 15 registered users, this will be a graveyard of empty geography. The 'Ghost Pins for local clubs' idea in the draft is a band-aid that creates false expectations.

| Recommendation: Kill the Map for MVP |
| :---- |
| Replace it with a list-first Discovery UI. Show available players as cards sorted by proximity and level match. Add the map back as a toggle once you have 500+ users in a single city. The list creates perceived density; a map exposes scarcity. |

#### B. Four Tabs Is Too Much Surface Area for Day One

PLAY, IMPROVE, THE LAB, and THE CLUBHOUSE are each individually well-designed, but launching with all four means you are asking a first-time user to understand four different value propositions before they have played a single match through your app. A new user who opens the app and sees four tabs will explore each one, find most of them empty (no journal entries, no stats, no social feed), and conclude the app is unfinished.

| Recommendation: Launch with PLAY + Lightweight Profile |
| :---- |
| Tab 1 (PLAY) is your entire MVP. Everything else is a reward for engagement. Tab 2 (IMPROVE) can enter as a post-match prompt ('How did it go?') rather than a standalone tab. Tab 3 and Tab 4 should be hidden until users have enough data to make them meaningful (approximately 5+ logged matches). |

#### C. The Onboarding Asks Too Much, Too Soon

The broadcast setup requires availability, court status, and a hard cutoff. This is three decisions before the user has seen any value. Competitors like Playtomic let you browse courts and see activity before asking you to commit to anything.

* **Step 1:** Let them browse who is nearby and active (no commitment needed)
* **Step 2:** Let them tap 'I want to play' with just a sport and a time window (today/tomorrow)
* **Step 3:** Court details come during the match negotiation, not upfront

#### D. Score Logging Needs to Be Simpler

The 'Score Dial' concept is visually appealing but adds friction. Most amateur matches can be captured with a simple tap-based interface: tap the number of sets, tap who won each set, done. The ceremony should be in the celebration animation, not in the input method.

#### E. Notifications Are Under-Specified

The spec mentions haptics and push notifications but does not address the notification strategy holistically. At launch, push notifications are your primary re-engagement tool. Every notification must be crafted to pull the user back to a specific action. 'You have a new challenge' is good. 'Rival Found!' with a 30-minute countdown is better. This needs its own mini-spec.

## 3. MVP Scope: What Ships First

The MVP must answer one question with zero ambiguity: 'Can this app help me find someone to play tennis/padel/pickleball with, and make that match feel meaningful?' Everything else is post-validation scope.

### 3.1 The MVP Feature Set

| Feature | Scope | Status |
| :---- | :---- | :---- |
| **Auth & Onboarding** | Firebase Auth (Gmail, email). Profile: name, photo, sport(s), self-declared level, home region | Auth done; profile needs trim |
| **Discovery (List)** | Card-based feed of available players. Filter by sport, level, distance. No map. | Needs redesign |
| **Broadcast** | 'Ready to Play' with sport + time window only. Court status deferred to match chat. | Simplify existing |
| **Challenge & Accept** | Send challenge, accept/decline with timer. Push notifications. | Backend ready |
| **Match Card** | Opponent info, deep link to Maps/Waze, in-app chat (or WhatsApp deep link for MVP). | Partially built |
| **Score Logging** | Simple tap UI for set scores. Mutual verification. Dispute flagging. | Backend ready |
| **GSM Points (Basic)** | 1000-4000 scale. Points on win, bonus for beating higher level. Show on profile. | Scoring engine specced |
| **Post-Match Prompt** | Quick 'How did it go?' reflection (2 taps). Not a full journal. Feeds future scouting. | Reduce Tab 2 scope |
| **Share Victory** | Auto-generated Instagram Story card with score, names, GSM branding. | New (mobile) |

### 3.2 What Is Explicitly NOT in MVP

| Feature | Reason Deferred | When |
| :---- | :---- | :---- |
| Map view | Creates ghost town effect with low user density | 500+ users/city |
| Leagues (Round Robin) | Requires critical mass of engaged users to fill groups | v1.2 (Month 4+) |
| Tab 3: THE LAB (full) | Needs match history data to be useful | v1.1 (Month 3) |
| Tab 4: THE CLUBHOUSE | Social feed requires community activity | v1.2 (Month 4+) |
| AI Scouting / Danger Zone | Needs significant match volume for ML | v2.0 (Month 8+) |
| Skill DNA Radar Chart | Requires journal reflections pipeline | v1.1 (Month 3) |
| Charity / Ball Donation | No partner confirmed, complex payment flow | v2.0+ |
| Premium Subscription | Need free value proven before charging | v2.0 (Month 8+) |

| The MVP Test |
| :---- |
| If a user can open the app, find a player, challenge them, play a match, log the score, see their points go up, and share a victory card to Instagram within their first week, the MVP has succeeded. Everything else is optimization. |

## 4. Team Structure: Who You Need

Startups die from either building the wrong thing or not getting it in front of people fast enough. The team structure below is optimized for a seed-stage company targeting a public beta within 10-12 weeks.

### 4.1 Core Team (Hires 1-5)

| Role | Responsibility | Profile | Timing |
| :---- | :---- | :---- | :---- |
| **You (Product/CEO)** | Product decisions, specs, investor relations, early community building | Already in role | Now |
| **iOS Engineer** | SwiftUI app. Owns all mobile UI, state management, notifications | Senior. SwiftUI + Firebase experience | Immediate |
| **Backend Lead** | FastAPI services, Firestore, Cloud Functions, Cloud Run deployment | Senior Python. Your existing backend knowledge is strong; this person ships production infra | Immediate |
| **Designer** | UI/UX design in Figma. Translates the Cyber-Athletic language into production screens | Product designer with mobile portfolio. Part-time/contract is fine | Week 1 |
| **Community / Growth** | Local court partnerships, player recruitment, social media, early retention loops | Scrappy operator. Plays racket sports. Knows the Athens scene | Week 4 |

### 4.2 Phase 2 Additions (Month 3-4)

* **QA / Test Engineer:** As you approach public launch, you need someone hammering edge cases on the state machine and notification flows.
* **Second Mobile Engineer (or Full-Stack):** Android reach becomes necessary for broader adoption, or a second iOS dev to accelerate Tab 2/3 build-out.
* **Marketing / Content:** Once you have real match data and user stories, someone needs to turn those into social proof content.

### 4.3 What You Do NOT Need Yet

* A data scientist (you need data volume first)
* A DevOps engineer (Cloud Run + GitHub Actions CI/CD is sufficient)
* A CTO title (you are the technical product owner; the Backend Lead fills the engineering leadership gap)
* Android at MVP (iOS-first in your target demographic is the right call)

## 5. Timeline: From Code to Users

The timeline below assumes you start with the core team of 3 builders (you + iOS + backend) and a part-time designer, launching in Athens as the beachhead market.

### 5.1 Phase 0: Foundation (Weeks 1-3)

| Track | Week 1-2 | Week 3 | Owner |
| :---- | :---- | :---- | :---- |
| **Product** | Finalize MVP scope, resolve OQ-1 to OQ-5, write mobile screens spec | Design review with iOS engineer | You |
| **Design** | Figma screens for Discovery (list), Broadcast, Match Card, Score Log | Victory share card template, onboarding flow | Designer |
| **Backend** | Production Cloud Run deployment. Push notification infra (FCM). API audit for MVP endpoints | Scoring engine Phase 1 (SE-1 to SE-7) | Backend Lead |
| **Mobile** | Auth flow (done), project setup, navigation architecture, design system tokens | Discovery list UI, broadcast flow | iOS Engineer |
| **Marketing** | Landing page + waitlist. Instagram account. Identify 10 Athens tennis/padel clubs | Begin club outreach. Poster design for courts | You (until hire) |

### 5.2 Phase 1: Closed Alpha (Weeks 4-7)

Goal: 50 real users playing real matches through the app. This is the concierge validation phase.

| Track | Deliverables | Milestone | Owner |
| :---- | :---- | :---- | :---- |
| **Backend** | Complete scoring engine. Match lifecycle end-to-end. Triggers D1-D3 live. Freshness reconciliation tested. | API v1 stable | Backend Lead |
| **Mobile** | Full PLAY tab: Discovery list, broadcast, challenge/accept, match card, score logging, points display. | TestFlight build | iOS Engineer |
| **Product** | Daily dogfooding. Bug triage. User interviews with alpha testers. Retention metrics setup (Mixpanel/Amplitude). | Alpha feedback report | You |
| **Marketing** | Recruit 50 alpha testers from 3-4 Athens clubs. WhatsApp group for feedback. Physical QR code posters at courts. | 50 registered users | Community hire |

### 5.3 Phase 2: Public Beta (Weeks 8-12)

Goal: 500 users, 200+ logged matches, App Store listing live, first organic growth signals.

| Track | Deliverables | Milestone | Owner |
| :---- | :---- | :---- | :---- |
| **Backend** | Tab 3 Phase 1 (progression graph, basic stats). Post-match prompt endpoint. Share card generation support. | Lab v1 live | Backend Lead |
| **Mobile** | Post-match reflection flow. Basic profile with GSM points + match history. Victory share card. App Store submission. | App Store approved | iOS Engineer |
| **Product** | Retention analysis (D1/D7/D30). Funnel analysis (signup to first match). Feature prioritization for v1.1 based on data. | v1.1 roadmap locked | You |
| **Marketing** | App Store Optimization. Instagram content from real matches. Referral program ('Invite a rival'). Expand to 10+ Athens clubs. | 500 users | Community + You |

### 5.4 Phase 3: Growth (Months 4-6)

Goal: 2000+ users, second city expansion, league pilot, monetization hypothesis testing.

* **Engineering:** Tab 2 (IMPROVE) as standalone tab. Tab 3 Phases 2-3 (Skill DNA, leaderboards). Tab 4 (CLUBHOUSE) Phase 1. Android planning.
* **Product:** First round-robin league pilot in Athens. Premium feature scoping (AI scouting, advanced analytics). User segmentation analysis.
* **Marketing:** Expand to Thessaloniki or a padel-heavy European city. Club partnership program. Influencer seeding with competitive amateur players.

## 6. Competitive Positioning

The racket sports app market is active but fragmented. Understanding where GSM sits relative to incumbents is critical for positioning and fundraising narratives.

|  | Playtomic | Padel Mates | MatchUp | GSM |
| :---- | :---- | :---- | :---- | :---- |
| **Core Value** | Court booking | Court booking + community | Tournament management | Scoring standard + matchmaking |
| **Moat** | 6,000 club partnerships | Nordic club network | Organizer workflows | Player intelligence data |
| **Monetization** | Booking fees + SaaS | Booking fees | App purchase | Leagues + Premium (planned) |
| **Weakness** | No player intelligence | Poor app quality (reviews) | No matchmaking | No court booking (by design) |
| **Users** | 4.7M+ | ~100K | Niche (organizers) | Pre-launch |

| GSM's Strategic Wedge |
| :---- |
| Playtomic owns the 'where to play' problem (courts). GSM owns the 'who to play and why it matters' problem (scoring, rivalry, intelligence). These are complementary, not directly competitive. In the long run, GSM could integrate with Playtomic's court API rather than building court booking infrastructure. The scoring standard is the moat that cannot be replicated by adding a feature; it requires the network of players who trust it. |

## 7. Monetization Roadmap

Do not charge for anything until the core matchmaking loop is proven and sticky (target: 40%+ D7 retention). The path to revenue follows a deliberate sequence.

1. **League Entry Fees (Month 4-5):** Charge per league season. Even a modest fee validates willingness to pay and funds small prizes. Target: 15-25 EUR per player per season.

2. **GSM Pro Subscription (Month 8+):** Unlock advanced analytics (Skill DNA comparison, Danger Zone AI scouting, detailed rivalry stats). Target: 4.99-9.99 EUR/month.

3. **Club Partnership SaaS (Month 10+):** Offer clubs a dashboard showing their members' activity, league management tools, and 'Host a GSM League' functionality. This is the B2B play.

4. **Sponsored Leagues & Tournaments (Month 12+):** Once you have a brand and a scoring standard, racket brands (Babolat, Head, Wilson) will pay to sponsor community leagues.

## 8. Key Risks & Mitigations

| Risk | Impact | Mitigation |
| :---- | :---- | :---- |
| **Cold Start / Low Density** | Users open app, see no one nearby, churn instantly. This kills marketplace apps. | Hyper-local launch (Athens only). Manual seeding via club partnerships. WhatsApp as fallback matchmaking until density is sufficient. |
| **Score Integrity** | Players inflate scores or refuse to confirm losses. Scoring system loses trust. | Mutual verification requirement is already in the spec. Add 'reputation score' weight so frequent disputants are flagged. |
| **iOS-Only Limitation** | Excludes Android users who represent 70%+ of Greek market. | Accept this for alpha/beta. Plan Android or React Native port for Month 5-6. Web booking can bridge gap. |
| **Playtomic Adds Scoring** | Incumbent could bolt on a scoring system to their 4.7M user base. | Move fast. The scoring standard only has value if players trust it. First-mover advantage in scoring credibility matters. Playtomic's DNA is B2B (clubs); player intelligence is a different muscle. |
| **Feature Creep** | The spec is ambitious. Trying to ship everything delays the core loop. | This document. Ruthless MVP scoping. Ship PLAY tab first, validate, then expand. |

## 9. Immediate Next Steps (This Week)

The following actions move GSM from 'well-documented codebase' to 'product that people use':

1. **Resolve OQ-1 through OQ-5.** These open questions on Tab 4 are blocking finalization. But more importantly, resolving them forces product decisions that ripple across the whole app.

2. **Define the MVP scope in a single document.** Take the MVP table from Section 3 and turn it into a one-page brief your iOS engineer can execute against.

3. **Set up App Store Connect and TestFlight.** Getting the infrastructure for distribution ready now means you can ship alpha builds the moment screens are ready.

4. **Build a waitlist landing page.** A simple page with email capture, the Cyber-Athletic branding, and a 30-second explainer video. Run it past 5 tennis players you know for gut-check feedback.

5. **Start recruiting.** Post the iOS Engineer and Backend Lead roles today. The team is the bottleneck; every day without builders is a day the timeline slips.

| The Bottom Line |
| :---- |
| GSM has an unusually strong technical foundation for a pre-launch startup. The spec work is thorough, the architecture is sound, and the product vision is clear. What it needs now is not more specification. It needs fewer features, faster shipping, and real players using it on real courts. The scoring standard only becomes a moat when people are playing within it. Ship the PLAY tab. Get 50 people using it. Let the data tell you what to build next. |
