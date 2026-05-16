Problem Statement:
  Objective
  Build a software-only solution that automatically generates comprehensive Business Requirements Documents by ingesting data from multiple communication channels (emails, meeting transcripts, Slack messages, uploaded documents). It should filter noise, extract project-relevant information, and produce a structured, professional BRD. Optional human oversight can be used during review stages. The agent must support iterative editing of generated documents.
 
  Challenge
  Business requirements are scattered across emails, meetings, chat messages, and informal documents. Manually synthesizing this information into a coherent BRD is time-consuming and error-prone. Your mission is to create a platform that:
 
  - Integrates with communication tools (Gmail, Slack, meeting transcription services like Fireflies)
  - Intelligently filters collected data to extract only project-relevant information (requirements, decisions, stakeholder feedback, timelines)
  - Generates a structured BRD with sections including Executive Summary, Business Objectives, Stakeholder Analysis, Functional/Non-Functional Requirements, Assumptions, Success Metrics, and Timeline
  - Supports natural language edit requests to modify specific sections or the entire document
  - Citation and explainability of the data, through different data structures and algorithms.
 
  You may optionally add features to:
  - Detect conflicting requirements across different sources
  - Generate requirement traceability matrices
  - Summarize stakeholder sentiment and concerns
  - Present findings via dashboards or automated status reports
 
  Tools Allowed
  Any software-based stack — no hardware required.
 
  Key Focus
  Accurate information extraction from diverse sources, intelligent noise filtering, and production of clear, actionable business requirements documentation.



The data for the problem statement is this:


Problem Statement 2: BRD (Business Requirements Document) Agent
[](https://github.com/GDG-Cloud-New-Delhi/hackfest-2.0-dataset/blob/main/Internal_Recommendation_Doc.md#problem-statement-2-brd-business-requirements-document-agent)
What participants need: Realistic business communication data — emails, meeting transcripts, chat messages — that contain project requirements, decisions, stakeholder feedback, and timelines scattered across noisy conversations.
Primary Recommendation
[](https://github.com/GDG-Cloud-New-Delhi/hackfest-2.0-dataset/blob/main/Internal_Recommendation_Doc.md#primary-recommendation-1)
The Enron Email Dataset
🔗 [https://www.kaggle.com/datasets/wcukierski/enron-email-dataset](https://www.kaggle.com/datasets/wcukierski/enron-email-dataset)
📜 License: Public Domain (released by the Federal Energy Regulatory Commission as part of a public investigation; freely available)
Why this dataset is ideal:
~500,000 real emails from ~150 Enron employees — authentic business communication with project discussions, decisions, meeting scheduling, and stakeholder interactions buried in everyday noise.
Perfect for testing the noise filtering requirement: participants must extract project-relevant requirements from a sea of routine emails (lunch plans, FYIs, newsletters).
Contains real organizational hierarchy signals (to/cc/bcc patterns) useful for stakeholder analysis in BRDs.
Emails span multiple projects and time periods, so the agent can be tested on extracting requirements for a specific topic or timeline.
This is the gold standard for email NLP research — well understood, extensively used, zero licensing concerns.
Secondary Recommendation
[](https://github.com/GDG-Cloud-New-Delhi/hackfest-2.0-dataset/blob/main/Internal_Recommendation_Doc.md#secondary-recommendation-1)
AMI Meeting Corpus
🔗 [https://huggingface.co/datasets/knkarthick/AMI](https://huggingface.co/datasets/knkarthick/AMI) (HuggingFace — transcripts + summaries)
🔗 [https://groups.inf.ed.ac.uk/ami/corpus/](https://groups.inf.ed.ac.uk/ami/corpus/) (Full corpus)
📜 License: CC BY 4.0 (Creative Commons Attribution)
Why this is a strong complement:
279 meeting transcripts with summaries — around two-thirds are from a scenario-based design project where participants play roles (project manager, industrial designer, interface designer, marketing) taking a product from kickoff to completion.
The scenario meetings contain exactly what a BRD agent needs to extract: requirements discussions, design decisions, stakeholder disagreements, feature prioritization, and timelines.
Pre-existing abstractive and extractive summaries serve as ground truth for evaluating whether the BRD agent correctly identified key decisions.
CC BY 4.0 — fully open for any use with attribution.
Tertiary Option
[](https://github.com/GDG-Cloud-New-Delhi/hackfest-2.0-dataset/blob/main/Internal_Recommendation_Doc.md#tertiary-option-1)
Meeting Transcripts Dataset (Kaggle)
🔗 [https://www.kaggle.com/datasets/abhishekunnam/meeting-transcripts](https://www.kaggle.com/datasets/abhishekunnam/meeting-transcripts)
📜 License: Check Kaggle page (community-uploaded)
Why it's useful:
Simpler meeting transcript dataset for quick prototyping before testing on the larger AMI corpus.
Usage Guidance for Participants
[](https://github.com/GDG-Cloud-New-Delhi/hackfest-2.0-dataset/blob/main/Internal_Recommendation_Doc.md#usage-guidance-for-participants)
Combine Enron emails (as the "email channel") with AMI transcripts (as the "meeting transcript channel") to simulate the multi-channel ingestion the problem statement requires. Participants can also generate synthetic Slack messages from the Enron data to cover the chat channel requirement.