# Regulatory flags: EU / Germany

**Analysis, not legal advice.** Confirm with counsel. The feasibility checklist
(`scoring/feasibility.py`) raises these flags automatically; this page explains them. Laws and
application dates change (the EU AI Act timeline in particular has been subject to amendment
proposals), so always check the current text.

| Area | Rule | What it means for a design |
|---|---|---|
| Personal data | GDPR (legal basis, Art. 28 processor agreement, minimisation, retention, Art. 9 special categories) | Data processing agreement with the model provider; scrub PII at ingestion; retention policy per client |
| AI in employment | EU AI Act (recruitment and worker evaluation are high-risk use cases) | Avoid automated ranking of people; human decision; documentation; check current obligations |
| Employee monitoring (DE) | BetrVG §87(1) no. 6: works council co-determines technical systems able to monitor behaviour or performance | Team sync log mining needs a works agreement or notice; pod-level reporting by default |
| Marketing outreach (DE) | UWG §7: unsolicited advertising by email or phone needs prior consent (B2C; strict for B2B calls) | Speed-to-lead replies answer inbound enquiries; no cold outreach automation; drafts approved by a person |
| Bookkeeping (DE) | GoBD: traceability, immutability, retention of records | No unreviewed postings; keep an audit trail of AI suggestions |
| Professional secrecy (DE) | §203 StGB (e.g. health, legal and tax professions) | Client data from these professions only after expert review |
| Platforms | Ad platform and messaging policies | Ads created paused; follow platform rules on automation |
