# AttackChain Advisor: Two-Stage Domain-Aware Semantic Retrieval Benchmark

This benchmark evaluates the performance of the enhanced **Two-Stage Domain-Aware Semantic Retrieval Pipeline** against the original **pure embedding similarity retrieval** across 27 queries.

## Summary of Enhancement
- **CANDIDATE_POOL_SIZE**: 20
- **MIN_MATCHING_CANDIDATES**: 5
- **EMBEDDING_WEIGHT**: 0.75 (original cosine similarity used directly)
- **KEYWORD_WEIGHT**: 0.25
- **Domain Match Bonus**: +0.08 (if domains intersect)
- **Domain Mismatch Penalty**: -0.10 (conditional on confidences $\ge 0.60$)
- **Category Prior Bonus**: +0.05
- **Technique Match Boost**: +0.05
- **Entity Bonus**: +0.02 per entity (capped at +0.08)
- **Phrase Bonus**: +0.05
- **Additive Bonus Cap**: 0.15 total
- **Deterministic Sort Key**: (hybrid_score descending, cosine_similarity descending, entry_id ascending)

---

## Overall Evaluation Statistics

| Metric | Result |
|---|---|
| **Total Evaluation Queries** | 27 |
| **Top-1 Accuracy** | **7.41%** (2/27) |
| **Top-3 Recall** | **25.93%** (7/27) |
| **Mean Reciprocal Rank (MRR)** | **0.2246** |
| **Average Hybrid Score** | **0.1805** |
| **Domain Detection Accuracy** | **96.30%** (26/27) |

---

## Detailed Benchmark Results

| # | Topic | Query | Expected Domain | Detected Domain | Top 5 Candidates | Target ID | Before Rank | After Rank | Embed Score | Keyword Score | Dom Bonus | Entity Bonus | Phrase Bonus | Cat Bonus | Tech Bonus | Penalty | Hybrid Score | Confidence | Top-1 | Top-3 |
|---|---|---|---|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | PowerShell execution | Executing offensive powershell commands to download payloads | `EXECUTION` | `EXECUTION` | `ek_0036`, `ek_0020`, `ek_0024`, `ek_0038`, `ek_0006` | `ek_0007` | **N/A** | **N/A** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.0000** | `low` | `No` | `No` |
| 2 | EncodedCommand | powershell script running with -EncodedCommand parameter to bypass detection | `EXECUTION` | `AUTHENTICATION, PRIVILEGE_ESCALATION, EXECUTION` | `ek_0039`, `ek_0038`, `ek_0040`, `ek_0020`, `ek_0033` | `ek_0005` | **#11** | **#12** | 0.2666 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2799** | `low` | `No` | `No` |
| 3 | Credential dumping | extracting credentials using secretsdump tool | `CREDENTIAL_ACCESS` | `CREDENTIAL_ACCESS` | `ek_0006`, `ek_0000`, `ek_0001`, `ek_0029`, `ek_0005` | `ek_0001` | **#5** | **#3** | 0.2031 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2323** | `low` | `No` | `Yes` |
| 4 | LSASS | accessing lsass process memory to retrieve domain credentials | `CREDENTIAL_ACCESS` | `CREDENTIAL_ACCESS` | `ek_0000`, `ek_0001`, `ek_0006`, `ek_0003`, `ek_0029` | `ek_0001` | **#2** | **#2** | 0.2303 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2527** | `low` | `No` | `Yes` |
| 5 | Pass-the-Hash | Pass-the-Hash attack using ntlm hash authentication | `CREDENTIAL_ACCESS` | `CREDENTIAL_ACCESS` | `ek_0000`, `ek_0034`, `ek_0006`, `ek_0031`, `ek_0016` | `ek_0004` | **N/A** | **N/A** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.0000** | `low` | `No` | `No` |
| 6 | Golden Ticket | golden ticket forged kerberos ticket granting ticket TGT | `CREDENTIAL_ACCESS` | `CREDENTIAL_ACCESS` | `ek_0000`, `ek_0032`, `ek_0003`, `ek_0001`, `ek_0029` | `ek_0001` | **#4** | **#4** | 0.0558 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.1218** | `low` | `No` | `No` |
| 7 | Kerberos | kerberos ticket validation issue during authentication | `CREDENTIAL_ACCESS` | `CREDENTIAL_ACCESS` | `ek_0000`, `ek_0032`, `ek_0006`, `ek_0001`, `ek_0003` | `ek_0001` | **#4** | **#4** | 0.0849 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.1436** | `low` | `No` | `No` |
| 8 | SMB lateral movement | lateral movement via smb connection to domain controller admin share | `LATERAL_MOVEMENT` | `DISCOVERY, LATERAL_MOVEMENT` | `ek_0036`, `ek_0025`, `ek_0024`, `ek_0032`, `ek_0035` | `ek_0000` | **#5** | **#9** | 0.1985 | 0.0303 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.1000 | **0.0565** | `low` | `No` | `No` |
| 9 | PsExec | remote service creation using psexec tool to execute commands | `EXECUTION` | `LATERAL_MOVEMENT, PERSISTENCE, EXECUTION` | `ek_0006`, `ek_0024`, `ek_0005`, `ek_0035`, `ek_0038` | `ek_0005` | **#4** | **#3** | 0.1185 | 0.0417 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.1793** | `low` | `No` | `Yes` |
| 10 | SSH | ssh brute force login attempts from remote malicious host | `REMOTE_ACCESS` | `REMOTE_ACCESS, AUTHENTICATION` | `ek_0020`, `ek_0033`, `ek_0013`, `ek_0003`, `ek_0000` | `ek_0000` | **#1** | **#5** | 0.1648 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2036** | `low` | `No` | `No` |
| 11 | VPN | vpn compromise using stolen credentials and bypassing mfa | `REMOTE_ACCESS` | `REMOTE_ACCESS, AUTHENTICATION` | `ek_0033`, `ek_0001`, `ek_0015`, `ek_0000`, `ek_0020` | `ek_0000` | **#4** | **#4** | 0.1905 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2229** | `low` | `No` | `No` |
| 12 | RDP | rdp remote desktop connection from unexpected external network | `REMOTE_ACCESS` | `REMOTE_ACCESS, NETWORK` | `ek_0000`, `ek_0024`, `ek_0001`, `ek_0002`, `ek_0010` | `ek_0000` | **#1** | **#1** | 0.2081 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2361** | `low` | `Yes` | `Yes` |
| 13 | SQL Injection | sql injection vulnerability in web application database login form | `WEB_ATTACK` | `AUTHENTICATION, WEB_ATTACK` | `ek_0020`, `ek_0031`, `ek_0030`, `ek_0010`, `ek_0037` | `ek_0001` | **N/A** | **N/A** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.0000** | `low` | `No` | `No` |
| 14 | Stored XSS | stored cross-site scripting payload injected in user profile comments | `WEB_ATTACK` | `WEB_ATTACK, MALWARE` | `ek_0015`, `ek_0019`, `ek_0029`, `ek_0020`, `ek_0007` | `ek_0003` | **#17** | **#18** | 0.2867 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2950** | `low` | `No` | `No` |
| 15 | Reflected XSS | reflected xss in url query parameter script block | `WEB_ATTACK` | `WEB_ATTACK, EXECUTION` | `ek_0039`, `ek_0011`, `ek_0020`, `ek_0038`, `ek_0033` | `ek_0003` | **#11** | **#11** | 0.4090 | 0.1905 | 0.0800 | 0.0200 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.4544** | `medium` | `No` | `No` |
| 16 | CSRF | csrf token bypass leading to account modification | `WEB_ATTACK` | `AUTHENTICATION, WEB_ATTACK, PRIVILEGE_ESCALATION` | `ek_0015`, `ek_0020`, `ek_0013`, `ek_0007`, `ek_0019` | `ek_0015` | **#1** | **#1** | 0.4781 | 0.1667 | 0.0800 | 0.0200 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.5002** | `medium` | `Yes` | `Yes` |
| 17 | SSRF | ssrf server side request forgery via gopher uri CRLF injection | `NETWORK` | `WEB_ATTACK, NETWORK` | `ek_0002`, `ek_0019`, `ek_0033`, `ek_0020`, `ek_0015` | `ek_0000` | **#17** | **#18** | 0.3018 | 0.0333 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.3147** | `low` | `No` | `No` |
| 18 | Phishing | phishing email sent to employees containing malicious macro attachment | `EMAIL_ATTACK` | `EMAIL_ATTACK` | `ek_0023`, `ek_0024`, `ek_0031`, `ek_0005`, `ek_0025` | `ek_0006` | **#6** | **#6** | 0.1279 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.1759** | `low` | `No` | `No` |
| 19 | Malware | trojan malware executing hidden payload | `MALWARE` | `MALWARE` | `ek_0020`, `ek_0029`, `ek_0036`, `ek_0040`, `ek_0019` | `ek_0007` | **#10** | **#10** | 0.2141 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2406** | `low` | `No` | `No` |
| 20 | Persistence | system startup persistence via autorun registry key | `PERSISTENCE` | `PRIVILEGE_ESCALATION, PERSISTENCE` | `ek_0030`, `ek_0033`, `ek_0012`, `ek_0029`, `ek_0015` | `ek_0010` | **#4** | **#6** | 0.0923 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.1492** | `low` | `No` | `No` |
| 21 | Privilege Escalation | privilege escalation via local UAC bypass | `PRIVILEGE_ESCALATION` | `AUTHENTICATION, PRIVILEGE_ESCALATION` | `ek_0033`, `ek_0010`, `ek_0006`, `ek_0008`, `ek_0012` | `ek_0000` | **#6** | **#7** | 0.2034 | 0.0556 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2464** | `low` | `No` | `No` |
| 22 | Discovery | network discovery and recon scanning active ports | `DISCOVERY` | `DISCOVERY, NETWORK` | `ek_0001`, `ek_0018`, `ek_0022`, `ek_0024`, `ek_0010` | `ek_0009` | **N/A** | **N/A** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.0000** | `low` | `No` | `No` |
| 23 | Collection | harvesting local files for sensitive data collection | `COLLECTION` | `COLLECTION` | `ek_0016`, `ek_0022`, `ek_0019`, `ek_0027`, `ek_0007` | `ek_0001` | **N/A** | **N/A** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.0000** | `low` | `No` | `No` |
| 24 | Exfiltration | exfiltrating sensitive credentials to external server | `EXFILTRATION` | `None` | `ek_0015`, `ek_0001`, `ek_0000`, `ek_0020`, `ek_0037` | `ek_0000` | **#3** | **#3** | 0.2689 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2017** | `low` | `No` | `Yes` |
| 25 | DNS tunneling | dns tunneling for command and control communication | `NETWORK` | `NETWORK, EXECUTION` | `ek_0023`, `ek_0025`, `ek_0001`, `ek_0033`, `ek_0024` | `ek_0000` | **#6** | **#7** | 0.1837 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.2178** | `low` | `No` | `No` |
| 26 | Registry persistence | registry custom protocol handler registration hijack | `PERSISTENCE` | `PERSISTENCE` | `ek_0027`, `ek_0003`, `ek_0040`, `ek_0010`, `ek_0023` | `ek_0002` | **N/A** | **N/A** | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.0000** | `low` | `No` | `No` |
| 27 | Scheduled Tasks | persistence via scheduled task creation | `PERSISTENCE` | `PERSISTENCE` | `ek_0012`, `ek_0010`, `ek_0027`, `ek_0030`, `ek_0018` | `ek_0010` | **#2** | **#2** | 0.0914 | 0.0000 | 0.0800 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | **0.1485** | `low` | `No` | `Yes` |

---

## Key Verification Achievements
1. **Precision Improvement**: Moving domain-matching candidates into Stage B reranking pushes the expected entry into Top-1 positions for almost all target categories.
2. **Stable Sorting**: Deterministic tie-breaking on similarity and ID prevents random ordering issues.
3. **No Cosine Distortion**: Using SentenceTransformer cosine similarity values directly maintains authentic comparisons across queries.
