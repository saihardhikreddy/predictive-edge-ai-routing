# First Review Presentation Guide (21 Slides)

**Project Title:** Predictive Edge AI Routing for Offline Bluetooth Mesh Networks  
**Subtitle:** An AI-Native, Privacy-Preserving and Secure Communication Architecture  
**Team 8:**
- C Sai Hardhik Reddy (CB.AI.U4AID25112)
- Kavali Charan Saatvikh Reddy (CB.AI.U4AID5124)
- R Gagan Chowdary (CB.AI.U4AID25145)

**Course:** Introduction to Computer Networks (23AID206)  
**Instructor:** Dr. Sundharesan S  
**Date:** 21 August 2026  
**LaTeX Master File:** [`presentation.tex`](file:///d:/projects/Computer%20Networks/presentation.tex)  
**Overleaf Template Link:** [Overleaf Beamer Template](https://www.overleaf.com/project/new/template/19345?id=65231945&templateName=An+example+of+the+beamer+package&latexEngine=&texImage=texlive-full%3A2020.1&mainFile=)

---

## 📋 1. Overleaf Quick Start (1-Click)
1. Open the [Overleaf Template](https://www.overleaf.com/project/new/template/19345?id=65231945&templateName=An+example+of+the+beamer+package&latexEngine=&texImage=texlive-full%3A2020.1&mainFile=) or create a new blank project on [Overleaf](https://www.overleaf.com).
2. Open `main.tex` and paste the entire contents of [`presentation.tex`](file:///d:/projects/Computer%20Networks/presentation.tex).
3. Click **Recompile**. The 21 slides with exact colors, royal blue headers, custom rounded blocks, and TikZ network diagrams will render.

---

## 🎙️ 2. Slide-by-Slide Speaking Script (15--20 Minutes)

### Slide 1: Title Slide
> *"Respected Dr. Sundharesan S and evaluators, good morning. We are Team 8, presenting our first review on **'Predictive Edge AI Routing for Offline Bluetooth Mesh Networks: An AI-Native, Privacy-Preserving and Secure Communication Architecture.'** Team members are C Sai Hardhik Reddy, Kavali Charan Saatvikh Reddy, and R Gagan Chowdary."*

### Slide 2: The Need for Offline Communication
> *"Modern communication relies heavily on cellular, Wi-Fi, and centralized internet infrastructure. However, during natural disasters, network outages, crowded festivals, or in remote zones, this infrastructure collapses. Offline peer-to-peer Bluetooth mesh allows nearby smartphones to act as relay nodes to keep communication alive."*

### Slide 3: Existing Offline Mesh Communication
> *"Existing offline messengers like Bridgefy, Briar, BitChat, and Meshtastic prove that offline mesh is feasible. However, their major limitation is reliance on flooding-based protocols, which cause severe broadcast storms, high battery drain, and unmanaged latency in dynamic crowds. Our motivation is to replace blind flooding with adaptive edge intelligence."*

### Slide 4: From Blind Flooding to Intelligent Routing
> *"In traditional flooding, each message is duplicated to every neighbor, causing an exponential increase in transmissions, RF congestion, and battery drain. In our proposed predictive routing, each node evaluates nearby candidate relays and selects the single most promising next-hop: **Observe $\to$ Predict $\to$ Select $\to$ Forward**."*

### Slide 5: Literature Review
> *"We reviewed seminal literature across RL for DTNs (rl4dtn), MARL dynamic routing (DRAMA), edge federated learning, and mesh security (Breaking Bridgefy). The identified research gap is clear: **no existing architecture combines MARL routing, semantic LLM priority, decentralized Gossip Federated Learning, and GNN topology defense in a single offline mesh.**"*

### Slide 6 & 7: Objectives and Significance
> *"Our project has five core pillars: 1) Intelligent MARL routing; 2) Network transmission efficiency; 3) Semantic priority via local SLM; 4) Privacy-preserving Gossip FL; and 5) GNN intrusion detection. This creates an offline network that is **intelligent, collaborative, privacy-preserving, and self-protecting**."*

### Slide 8 & 9: Problem Statement & Importance
> *"Our core research question: How can an offline Bluetooth mesh select forwarding nodes while minimizing overhead, protecting privacy, and isolating malicious nodes? Without intelligence, flooding leads to broadcast collapse. With our routing, selective and energy-aware forwarding ensures emergency survivability."*

### Slide 10: Key Deliverables and Milestones
> *"We have structured our work into 9 formal milestones (M1 to M9) spanning problem identification, 4-layer architecture design, MARL state-action formulation, dynamic mesh simulation, local LLM integration, Gossip FL, GNN security, and final performance evaluation."*

### Slide 11: Proposed System Architecture
> *"Our 4-layer AI-native architecture processes messages through: 1) **Local LLM/SLM** for intent detection & compression; 2) **MARL Routing Engine** evaluating battery, buffer, mobility, and encounters; 3) **Gossip Federated Learning** for peer-to-peer model updates; and 4) **GNN Security Layer** for anomaly detection before physical transmission over the Bluetooth Mesh."*

### Slide 12: MARL-Based Predictive Routing
> *"Each node observes its state (battery, buffer, mobility vector, encounter history). The action space selects whether to forward to a promising peer, forward to a high-contact peer, or hold the message. Rewards reward successful delivery while penalizing dropped packets and battery waste."*

### Slide 13: Local LLM + Gossip Federated Learning
> *"For high-priority situations, our local SLM takes raw verbose text (e.g. 'Help! A building collapsed and people are trapped') and distills it into an 18-byte token payload (`CRITICAL_SOS: Building collapse`). Gossip FL allows nodes to exchange model weight updates during encounters without ever leaking raw user location coordinates."*

### Slide 14: GNN-Based Security Layer
> *"Rather than inspecting encrypted payloads, our GNN IDS analyzes topological behavior (connection frequencies, packet drop rates, routing score anomalies). When a rogue sinkhole fakes high routing reputation, the GNN detects the anomaly and isolates the node."*

### Slide 15 & 16: Progress So Far & A/B Demonstration Plan
> *"For Phase 1, we have completed problem formulation, literature review, the four-layer architecture, and MARL state-action models. We designed an A/B demonstration plan comparing **Mode A (LLM Off: Pure Predictive Routing)** with **Mode B (LLM On: Cognitive Emergency Routing)**."*

### Slide 17 & 18: Challenges, Risks & Timeline Roadmap
> *"We have identified mitigations for dynamic topology, non-stationarity, cold-start, and mobile compute constraints. Our upcoming phases cover Phase 1 (MARL simulation), Phase 2 (Local LLM / Ollama), Phase 3 (Gossip FL), and Phase 4 (GNN security training)."*

### Slide 19 & 20: Evaluation Plan & Conclusion
> *"We will benchmark Packet Delivery Ratio, Latency, Transmissions, Battery Cost, and Drop Rate across Flooding vs. MARL vs. MARL+LLM. In conclusion, we are transitioning offline mesh networks from **'Broadcast to Everyone'** to **'Predict, Prioritize, and Securely Forward.'**"*

### Slide 21: Thank You & Q&A
> *"Thank you. We are open for questions."*
